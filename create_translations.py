import os
import sys
import time
import json
import math
import zipfile
import itertools
import threading
from typing import Dict, Tuple, Optional

import polib
import requests
from dotenv import load_dotenv
from colorama import Fore, Style, init as colorama_init
from tqdm import tqdm

# Optional providers
_PROVIDER_GOOGLE = True
_PROVIDER_MEMORY = True

try:
    from googletrans import Translator as GoogleTranslator  # googletrans==4.0.0-rc1
except Exception:
    _PROVIDER_GOOGLE = False

try:
    from deep_translator import MyMemoryTranslator
except Exception:
    _PROVIDER_MEMORY = False

colorama_init(autoreset=True)
load_dotenv()

# ---------------- SETTINGS ----------------
POT_FILE = os.getenv("POT_FILE", "").strip()
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
LANG_FILE = os.path.join(DATA_DIR, "languages.json")
LOCALE_MAP_FILE = os.path.join(DATA_DIR, "locale_map.json")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "languages")

# Spinner / icons (PowerShell/cmd safe enough these days)
ICONS = {
    "start": "🚀",
    "ok": "✅",
    "warn": "⚠️",
    "err": "❌",
    "info": "ℹ️",
    "zip": "📦",
    "file": "💾",
    "globe": "🌍",
    "bolt": "⚡",
    "loop": "🔁",
    "star": "✨",
    "book": "📘",
}

# Public LibreTranslate fallback endpoint
LIBRE_URL = "https://libretranslate.com/translate"

# Default provider order (can override via CLI)
DEFAULT_PROVIDER_CHAIN = ["google", "mymemory", "libre"]
# -------------------------------------------


def load_json(path: str, required: bool = True):
    if not os.path.exists(path):
        if required:
            print(Fore.RED + f"{ICONS['err']} Missing required file: {path}")
            sys.exit(1)
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def normalize_lang_for_provider(lang_code: str, provider: str) -> str:
    """
    Normalize a general language code to what each provider expects.
    - googletrans prefers: 'zh-cn', 'pt', 'es', etc.
    - MyMemory often accepts BCP-47 like 'zh-CN' but also simple tags; we pass through.
    - LibreTranslate uses ISO codes: 'zh', 'pt', etc., with 'zh' for Chinese.
    """
    lc = lang_code.lower()

    if provider == "google":
        # googletrans: supports 'zh-cn', 'zh-tw'
        if lc in ["zh", "zh_cn", "zh-cn", "zh-hans", "zh_sg", "zh_hans"]:
            return "zh-cn"
        if lc in ["zh_tw", "zh-tw", "zh-hant"]:
            return "zh-tw"
        return lc

    if provider == "mymemory":
        # MyMemory can handle 'zh-CN' better sometimes
        if lc in ["zh", "zh_cn", "zh-cn", "zh-hans"]:
            return "ZH-CN"
        if lc in ["zh_tw", "zh-tw", "zh-hant"]:
            return "ZH-TW"
        # Hebrew sometimes expects 'he'
        if lc == "iw":
            return "he"
        return lc

    if provider == "libre":
        # LibreTranslate common list uses 'zh' for Chinese simplified.
        if lc in ["zh", "zh-cn", "zh_cn", "zh-hans"]:
            return "zh"
        if lc in ["zh_tw", "zh-tw", "zh-hant"]:
            return "zh"  # Libre may not split; still try 'zh'
        # he vs iw
        if lc == "iw":
            return "he"
        return lc

    return lc


def spinner(text: str, stop_event: threading.Event, position: int = 0):
    # Simple CLI spinner; we keep it short to avoid flicker with tqdm
    for c in itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]):
        if stop_event.is_set():
            break
        tqdm.write(Fore.YELLOW + f"{ICONS['loop']} {text} {c}")
        time.sleep(0.2)


def translate_with_chain(text: str, lang_code: str, provider_chain, max_retries=3) -> Tuple[str, str]:
    """
    Try providers in order; immediately retry failures up to max_retries (1s, 3s, 5s).
    Returns: (translated_text, provider_used)
    """
    text = text.strip()
    if not text:
        return "", "skip"

    last_err = None
    for provider in provider_chain:
        # Skip if unavailable
        if provider == "google" and not _PROVIDER_GOOGLE:
            continue
        if provider == "mymemory" and not _PROVIDER_MEMORY:
            continue

        normalized = normalize_lang_for_provider(lang_code, provider)
        for attempt in range(1, max_retries + 1):
            delay = [1, 3, 5][min(attempt - 1, 2)]
            title = f"Trying {provider} (attempt {attempt}/{max_retries}) → {lang_code}"
            stop_event = threading.Event()
            t = threading.Thread(target=spinner, args=(title, stop_event))
            t.daemon = True
            t.start()

            try:
                if provider == "google":
                    translator = GoogleTranslator()
                    res = translator.translate(text, dest=normalized)
                    out = getattr(res, "text", None)
                elif provider == "mymemory":
                    mt = MyMemoryTranslator(to_lang=normalized)
                    out = mt.translate(text)
                elif provider == "libre":
                    payload = {
                        "q": text,
                        "source": "auto",
                        "target": normalized,
                        "format": "text",
                    }
                    r = requests.post(LIBRE_URL, data=payload, timeout=12)
                    if r.status_code == 200:
                        out = r.json().get("translatedText")
                    else:
                        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:120]}")
                else:
                    raise RuntimeError("Unknown provider")

                stop_event.set()
                t.join()
                tqdm.write(Fore.GREEN + f"{ICONS['ok']} {provider} → success")
                if out:
                    return out, provider
                else:
                    raise RuntimeError("Empty translation received")

            except Exception as e:
                stop_event.set()
                t.join()
                last_err = str(e)
                tqdm.write(Fore.RED + f"{ICONS['err']} {provider} failed: {last_err}")
                if attempt < max_retries:
                    tqdm.write(Fore.YELLOW + f"{ICONS['warn']} retrying in {delay}s...")
                    time.sleep(delay)

                # Clear between retries (anti-flicker)
                # (No explicit console clear; just visual separator)
                tqdm.write(Style.DIM + "—" * 40)

        # move to next provider
        tqdm.write(Fore.YELLOW + f"{ICONS['warn']} switching provider...")

    # Ultimate fallback: mirror
    return f"{text} ({lang_code})", "mirror"


def ensure_output_dir():
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def base_name_from_pot(pot_path: str) -> str:
    # strip extension only; leave the rest intact
    return os.path.splitext(os.path.basename(pot_path))[0]


def save_zip(zip_output: bool):
    if not zip_output:
        return
    zip_path = os.path.join(OUTPUT_DIR, "translations.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for f in os.listdir(OUTPUT_DIR):
            if f.endswith((".po", ".mo")):
                zipf.write(os.path.join(OUTPUT_DIR, f), f)
    print(Fore.YELLOW + f"{ICONS['zip']} Zipped translations into {zip_path}")


def colorful_summary(summary_rows):
    if not summary_rows:
        return
    # Determine widths
    headers = ["Language", "Locale", "Entries", "Translated", "Provider Hits"]
    widths = [12, 10, 8, 11, 20]

    def fmt_row(row):
        return (
            f"{row[0]:<{widths[0]}}  {row[1]:<{widths[1]}}  "
            f"{row[2]:>{widths[2]}}  {row[3]:>{widths[3]}}  {row[4]:<{widths[4]}}"
        )

    print(Fore.CYAN + "\n" + ICONS["star"] + " Translation Summary\n")
    print(Fore.WHITE + fmt_row(headers))
    print(Style.DIM + "-" * (sum(widths) + 8))
    for r in summary_rows:
        print(Fore.GREEN + fmt_row(r))
    print("")


def generate_translations(provider_chain, max_retries=3, zip_output=False):
    if not POT_FILE or not os.path.exists(POT_FILE):
        print(Fore.RED + f"{ICONS['err']} POT file not found or not set: {POT_FILE!r}")
        print(Fore.YELLOW + f"{ICONS['info']} Set POT_FILE in your .env, e.g. POT_FILE=/full/path/aio-time-clock-lite.pot")
        sys.exit(1)

    langs: Dict[str, str] = load_json(LANG_FILE, required=True)
    locale_map: Dict[str, str] = load_json(LOCALE_MAP_FILE, required=True)

    ensure_output_dir()
    pot = polib.pofile(POT_FILE)
    total_entries = len(pot)
    base_name = base_name_from_pot(POT_FILE)

    print(Fore.CYAN + f"\n{ICONS['start']} Starting translations for {len(langs)} languages...")
    print(Fore.CYAN + f"{ICONS['book']} Input: {POT_FILE}")
    print(Fore.CYAN + f"{ICONS['file']} Output folder: {OUTPUT_DIR}\n")

    summary = []

    for lang_code, lang_name in langs.items():
        locale = locale_map.get(lang_code, lang_code)
        po_path = os.path.join(OUTPUT_DIR, f"{base_name}-{locale}.po")
        mo_path = os.path.join(OUTPUT_DIR, f"{base_name}-{locale}.mo")

        print(Fore.MAGENTA + f"\n{ICONS['globe']} Translating to {lang_name} ({lang_code})  →  locale {locale}\n")

        # Fresh PO file with copied metadata
        po = polib.POFile()
        po.metadata = pot.metadata.copy()

        # Keep a provider usage tally
        provider_hits = {"google": 0, "mymemory": 0, "libre": 0, "mirror": 0, "skip": 0}

        # Single antiflicker status bar at the bottom
        with tqdm(
            total=total_entries,
            desc=f"{lang_name[:16]}",
            ncols=90,
            colour="green",
            leave=True,
            dynamic_ncols=True,
        ) as bar:

            log_buffer = []
            last_flush_i = 0

            for i, entry in enumerate(pot, start=1):
                msgid = entry.msgid or ""
                msgid = msgid.strip()

                if not msgid:
                    po.append(entry)
                    bar.update(1)
                    continue

                tqdm.write(Fore.WHITE + f"🔹 {msgid}")

                translated, used = translate_with_chain(
                    msgid, lang_code, provider_chain=provider_chain, max_retries=max_retries
                )
                provider_hits[used] = provider_hits.get(used, 0) + 1

                new_entry = polib.POEntry(
                    msgid=entry.msgid,
                    msgstr=translated,
                    msgctxt=entry.msgctxt,
                )
                po.append(new_entry)

                log_buffer.append(Fore.GREEN + f"{ICONS['ok']} → {translated}")

                # Flush logs in chunks (anti-flicker). Keep the status bar stationary at bottom.
                if (i - last_flush_i) >= 5 or i == total_entries:
                    for line in log_buffer:
                        tqdm.write(line)
                    log_buffer = []
                    last_flush_i = i

                bar.update(1)
                # Small sleep reduces redraw thrash in some terminals
                time.sleep(0.01)

        # Save .po and .mo
        po.save(po_path)
        po.save_as_mofile(mo_path)
        print(Fore.GREEN + f"{ICONS['file']} Saved {po_path}")
        print(Fore.GREEN + f"{ICONS['file']} Saved {mo_path}")

        # Build a compact provider summary string
        prov_str = ", ".join([f"{k}:{v}" for k, v in provider_hits.items() if v])
        summary.append([lang_name, locale, str(total_entries), str(total_entries), prov_str])

    print(Fore.CYAN + f"\n{ICONS['ok']} All translations complete!\n")
    colorful_summary(summary)
    save_zip(zip_output)


def parse_args():
    import argparse
    p = argparse.ArgumentParser(description="Translate a POT file into multiple languages (.po/.mo).")
    p.add_argument("--zip", action="store_true", help="Zip all translations into translations.zip")
    p.add_argument("--max-retries", type=int, default=3, help="Max retries per provider (default 3)")
    p.add_argument(
        "--providers",
        type=str,
        default=",".join(DEFAULT_PROVIDER_CHAIN),
        help="Comma list of providers in order (google,mymemory,libre)",
    )
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    provider_chain = [x.strip().lower() for x in args.providers.split(",") if x.strip()]
    generate_translations(provider_chain=provider_chain, max_retries=args.max_retries, zip_output=args.zip)
