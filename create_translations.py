import os
import sys
import time
import json
import zipfile
import itertools
import threading
from typing import Dict, Tuple

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

try:
    from InquirerPy import inquirer
    HAVE_INQUIRER = True
except ImportError:
    HAVE_INQUIRER = False

colorama_init(autoreset=True)
load_dotenv()

# ---------------- SETTINGS ----------------
POT_FILE = os.getenv("POT_FILE", "").strip()
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
LANG_FILE = os.path.join(DATA_DIR, "languages.json")
LOCALE_MAP_FILE = os.path.join(DATA_DIR, "locale_map.json")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "languages")

ICONS = {
    "start": "🚀",
    "ok": "✅",
    "warn": "⚠️",
    "err": "❌",
    "info": "ℹ️",
    "zip": "📦",
    "file": "💾",
    "globe": "🌍",
    "loop": "🔁",
    "star": "✨",
    "book": "📘",
}

# Public LibreTranslate primary + fallback mirrors
LIBRE_MIRRORS = [
    "https://libretranslate.com/translate",             # official (may need key)
    "https://translate.argosopentech.com/translate",    # Argos OpenTech free
    "https://libretranslate.de/translate",              # Germany mirror
    "https://translate.astian.org/translate",           # Chile mirror
    "https://translate.fortytwo-it.com/translate",      # Italy mirror
]
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
    Map UI/BCP-47 tags (es-MX, pt-BR, zh-CN...) to what each provider actually accepts.
    """
    lc = lang_code.strip().lower()
    primary = lc.split("-")[0]

    def to_locale(code):
        parts = code.replace("_", "-").split("-")
        if len(parts) == 1:
            return parts[0].lower()
        return parts[0].lower() + "-" + parts[1].upper()

    if provider == "google":
        # googletrans prefers base codes; special-cases:
        # zh: zh-cn / zh-tw, he: iw, pt-BR → pt
        if lc in {"zh", "zh_cn", "zh-cn", "zh-hans", "zh_sg"}:
            return "zh-cn"
        if lc in {"zh_tw", "zh-tw", "zh-hant"}:
            return "zh-tw"
        if primary == "zh":
            return "zh-cn"
        if lc in {"he", "he-il", "iw", "iw-il"}:
            return "iw"
        if lc in {"pt-br", "pt_br"}:
            return "pt"
        # Any regional like es-mx, fr-ca → base
        if "-" in lc:
            return primary
        return lc

    if provider == "mymemory":
        # MyMemory expects very specific locale codes; base -> canonical locale
        CANON = {
            "es": "es-ES", "fr": "fr-FR", "de": "de-DE", "it": "it-IT",
            "pt": "pt-PT", "sv": "sv-SE", "nl": "nl-NL", "ru": "ru-RU",
            "ar": "ar-SA", "he": "he-IL", "tr": "tr-TR", "vi": "vi-VN",
            "ko": "ko-KR", "ja": "ja-JP", "pl": "pl-PL", "ro": "ro-RO",
            "cs": "cs-CZ", "da": "da-DK", "fi": "fi-FI", "hu": "hu-HU",
            "el": "el-GR", "uk": "uk-UA",
            # Chinese variants
            "zh": "zh-CN",
        }
        # specific region we want to keep (supported in their list)
        if lc in {"pt-br", "pt_br"}:
            return "pt-BR"
        if lc in {"zh", "zh_cn", "zh-cn", "zh-hans"}:
            return "zh-CN"
        if lc in {"zh_tw", "zh-tw", "zh-hant"}:
            return "zh-TW"
        if lc == "es-mx":
            return "es-MX"  # keep Mexican Spanish if asked
        if "-" in lc:
            return to_locale(lc)  # e.g., es-mx -> es-MX
        return CANON.get(primary, primary)

    if provider == "libre":
        # LibreTranslate mostly wants base codes
        if primary == "zh":
            return "zh"
        if lc in {"he", "iw", "he-il", "iw-il"}:
            return "he"
        if "-" in lc:
            return primary
        return lc

    return lc

def spinner(text: str, stop_event: threading.Event):
    for c in itertools.cycle(["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]):
        if stop_event.is_set():
            break
        tqdm.write(Fore.YELLOW + f"{ICONS['loop']} {text} {c}")
        time.sleep(0.2)

def translate_with_chain(text: str, lang_code: str, provider_chain, max_retries=3) -> Tuple[str, str]:
    text = text.strip()
    if not text:
        return "", "skip"

    for provider in provider_chain:
        if provider == "google" and not _PROVIDER_GOOGLE:
            continue
        if provider == "mymemory" and not _PROVIDER_MEMORY:
            continue

        normalized = normalize_lang_for_provider(lang_code, provider)

        for attempt in range(1, max_retries + 1):
            delay = [1, 3, 5][min(attempt - 1, 2)]
            stop_event = threading.Event()
            t = threading.Thread(target=spinner, args=(f"{provider} → {lang_code}", stop_event))
            t.daemon = True
            t.start()

            try:
                out = None
                if provider == "google":
                    translator = GoogleTranslator()
                    try:
                        res = translator.translate(text, dest=normalized)
                    except Exception:
                        # If a region slipped through (e.g., es-mx), retry with primary subtag
                        fallback_dest = normalized.split("-")[0].split("_")[0]
                        res = translator.translate(text, dest=fallback_dest)
                    out = getattr(res, "text", None)

                elif provider == "mymemory":
                    # Set explicit English source to avoid "en not supported" noise.
                    tgt = normalized
                    try:
                        mt = MyMemoryTranslator(source="en-US", target=tgt)
                        out = mt.translate(text)
                    except Exception as e:
                        # If target is a regional that failed, try es-ES as a safe fallback.
                        msg = str(e).lower()
                        # Compress the giant dict message
                        if "please select on" in msg and "supported languages" in msg:
                            tqdm.write(Fore.YELLOW + "⚠️  MyMemory rejected the code; retrying with a safer target…")
                        # Prefer es-ES for any Spanish failure, else strip to base
                        if tgt.lower().startswith("es") and tgt.lower() != "es-es":
                            try:
                                mt2 = MyMemoryTranslator(source="en-US", target="es-ES")
                                out = mt2.translate(text)
                            except Exception:
                                out = None
                        elif "-" in tgt:
                            base = tgt.split("-")[0]
                            # Some bases still need region; try a sensible default
                            fallback = {"pt": "pt-PT", "he": "he-IL"}.get(base, base)
                            try:
                                mt2 = MyMemoryTranslator(source="en-US", target=fallback)
                                out = mt2.translate(text)
                            except Exception:
                                out = None
                        else:
                            out = None

                elif provider == "libre":
                    for mirror in LIBRE_MIRRORS:
                        try:
                            payload = {"q": text, "source": "auto", "target": normalized, "format": "text"}
                            r = requests.post(mirror, data=payload, timeout=10)
                            if r.status_code == 200:
                                out = r.json().get("translatedText")
                                tqdm.write(Fore.GREEN + f"🌐 Libre success via {mirror}")
                                break
                            elif r.status_code in (401, 403):
                                tqdm.write(Fore.YELLOW + f"⚠️ Libre requires key: {mirror}")
                                continue
                        except Exception as e:
                            tqdm.write(Fore.RED + f"❌ Libre error {e}")
                            continue

                stop_event.set()
                t.join()

                if out and out.strip():
                    tqdm.write(Fore.GREEN + f"{ICONS['ok']} {provider} succeeded")
                    return out, provider

                # If we used a regional tag (xx-yy), attempt a one-off retry with the base (xx)
                # before declaring failure for this provider.
                if "-" in lang_code:
                    base = lang_code.split("-")[0]
                    base_norm = normalize_lang_for_provider(base, provider)
                    try:
                        if provider == "google":
                            translator = GoogleTranslator()
                            res2 = translator.translate(text, dest=base_norm)
                            out2 = getattr(res2, "text", None)
                        elif provider == "mymemory":
                            mt2 = MyMemoryTranslator(to_lang=base_norm)
                            out2 = mt2.translate(text)
                        elif provider == "libre":
                            out2 = None
                            for mirror in LIBRE_MIRRORS:
                                payload = {"q": text, "source": "auto", "target": base_norm, "format": "text"}
                                r = requests.post(mirror, data=payload, timeout=10)
                                if r.status_code == 200:
                                    out2 = r.json().get("translatedText")
                                    if out2:
                                        tqdm.write(Fore.GREEN + f"🌐 Libre success via {mirror} (base={base_norm})")
                                        break
                        else:
                            out2 = None

                        if out2 and out2.strip():
                            tqdm.write(Fore.GREEN + f"{ICONS['ok']} {provider} recovered with base code '{base_norm}'")
                            return out2, provider
                    except Exception as e2:
                        tqdm.write(Fore.YELLOW + f"{ICONS['warn']} {provider} base retry failed: {e2}")

                raise RuntimeError("Empty result")


            except Exception as e:
                stop_event.set()
                t.join()
                tqdm.write(Fore.RED + f"{ICONS['err']} {provider} failed: {e}")
                msg = str(e)
                if "Please select on of the supported languages" in msg:
                    msg = "Unsupported language tag for this provider"
                tqdm.write(Fore.RED + f"{ICONS['err']} {provider} failed: {msg}")
                if attempt < max_retries:
                    tqdm.write(Fore.YELLOW + f"{ICONS['warn']} Retrying in {delay}s...")
                    time.sleep(delay)

        tqdm.write(Fore.YELLOW + f"{ICONS['warn']} Switching provider...")
    return f"{text} ({lang_code})", "mirror"

def ensure_output_dir():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

def base_name_from_pot(pot_path: str) -> str:
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
    headers = ["Language", "Locale", "Entries", "Provider Hits"]
    widths = [18, 12, 10, 25]
    def fmt_row(row):
        return f"{row[0]:<{widths[0]}}  {row[1]:<{widths[1]}}  {row[2]:>{widths[2]}}  {row[3]:<{widths[3]}}"
    print(Fore.CYAN + "\n" + ICONS["star"] + " Translation Summary\n")
    print(Fore.WHITE + fmt_row(headers))
    print(Style.DIM + "-" * (sum(widths) + 8))
    for r in summary_rows:
        print(Fore.GREEN + fmt_row(r))
    print("")

def prompt_language_selection(all_langs, no_menu: bool = False):
    """
    Default: interactive space-bar checkbox menu (InquirerPy) **when available**.
    Adds a synthetic 'All languages' option; selecting it means 'use them all'.
    Falls back to numeric input when:
      - --no-menu is passed
      - InquirerPy not installed
      - not a TTY (e.g., IDE run console, pipes, CI)
    """
    ALL_TOKEN = "__ALL_LANGS__"
    pretty = lambda l: f"{l['name']} ({l['code']})"

    # Build choices with an 'All languages' item at the top
    choices = [("✅ All languages", ALL_TOKEN)] + [(pretty(l), l["code"]) for l in all_langs]

    def _numeric_fallback():
        print(Fore.YELLOW + "⚠️ Interactive menu unavailable — using numeric fallback.\n")
        print("0. ✅ All languages")
        for i, (_, code) in enumerate(choices[1:], start=1):
            # choices[i] maps to all_langs[i-1]
            print(f"{i}. {pretty(all_langs[i-1])}")
        raw = input("\nEnter numbers separated by commas (e.g., 0 or 1,3,4): ").strip()
        idxs = [int(x) for x in raw.split(",") if x.strip().isdigit()]
        if 0 in idxs:
            return list(all_langs)
        idxs = [i for i in idxs if 1 <= i <= len(all_langs)]
        return [all_langs[i-1] for i in idxs]

    want_menu = not no_menu
    if want_menu and HAVE_INQUIRER and sys.stdin.isatty() and sys.stdout.isatty():
        try:
            # InquirerPy expects simple list of labels, so keep a parallel map
            labels = [c[0] for c in choices]
            selected = inquirer.checkbox(
                message="Select languages (Space to toggle, Enter to confirm):",
                choices=labels,
                cycle=True,
                instruction="Tip: choose “✅ All languages” to select everything",
                transformer=lambda result: f"{len(result)} selected",
            ).execute()

            # If 'All languages' picked → return all
            if labels[0] in selected:
                return list(all_langs)

            # Otherwise map labels back to codes, then to language dicts
            selected_codes = {
                choices[labels.index(lbl)][1] for lbl in selected
            }
            return [l for l in all_langs if l["code"] in selected_codes]
        except Exception as e:
            print(Fore.YELLOW + f"⚠️ Menu failed ({e}). Falling back.\n")
            return _numeric_fallback()
    else:
        return _numeric_fallback()
    
def generate_translations(selected_langs, provider_chain, max_retries=3, zip_output=False):
    if not POT_FILE or not os.path.exists(POT_FILE):
        print(Fore.RED + f"{ICONS['err']} POT file not found or not set: {POT_FILE!r}")
        sys.exit(1)

    locale_map: Dict[str, str] = load_json(LOCALE_MAP_FILE, required=True)
    ensure_output_dir()
    pot = polib.pofile(POT_FILE)
    total_entries = len(pot)
    base_name = base_name_from_pot(POT_FILE)

    print(Fore.CYAN + f"\n{ICONS['start']} Translating {len(selected_langs)} languages...")
    print(Fore.CYAN + f"{ICONS['book']} Input: {POT_FILE}")
    print(Fore.CYAN + f"{ICONS['file']} Output folder: {OUTPUT_DIR}\n")

    summary = []
    for lang in selected_langs:
        lang_code, lang_name = lang["code"], lang["name"]
        locale = locale_map.get(lang_code, lang_code)
        po_path = os.path.join(OUTPUT_DIR, f"{base_name}-{locale}.po")
        mo_path = os.path.join(OUTPUT_DIR, f"{base_name}-{locale}.mo")
        print(Fore.MAGENTA + f"\n{ICONS['globe']} {lang_name} ({lang_code}) → locale {locale}\n")
        po = polib.POFile()
        po.metadata = pot.metadata.copy()

        # Add language code to headers
        po.metadata["Language"] = locale.replace("-", "_")
        po.metadata.setdefault("Language-Team", f"{lang_name} <LL@li.org>")
        po.metadata.setdefault("X-Generator", "wordpress-translator-bot")
        provider_hits = {"google": 0, "mymemory": 0, "libre": 0, "mirror": 0, "skip": 0}

        with tqdm(total=total_entries, desc=f"{lang_name[:16]}", ncols=90, colour="green", leave=True) as bar:
            for i, entry in enumerate(pot, start=1):
                msgid = (entry.msgid or "").strip()
                if not msgid:
                    po.append(entry)
                    bar.update(1)
                    continue
                translated, used = translate_with_chain(msgid, lang_code, provider_chain, max_retries)
                provider_hits[used] += 1
                po.append(polib.POEntry(msgid=entry.msgid, msgstr=translated, msgctxt=entry.msgctxt))
                tqdm.write(Fore.GREEN + f"{ICONS['ok']} {msgid} → {translated}")
                bar.update(1)
                time.sleep(0.01)

        po.save(po_path)
        po.save_as_mofile(mo_path)
        prov_str = ", ".join([f"{k}:{v}" for k, v in provider_hits.items() if v])
        summary.append([lang_name, locale, str(total_entries), prov_str])
        print(Fore.GREEN + f"{ICONS['file']} Saved {po_path}\n")

    print(Fore.CYAN + f"\n{ICONS['ok']} All translations complete!\n")
    colorful_summary(summary)
    save_zip(zip_output)

def parse_args():
    import argparse
    p = argparse.ArgumentParser(description="Translate a POT file into multiple languages (.po/.mo).")
    p.add_argument("--zip", action="store_true", help="Zip all translations into translations.zip")
    p.add_argument("--max-retries", type=int, default=3, help="Max retries per provider (default 3)")
    p.add_argument("--providers", type=str, default=",".join(DEFAULT_PROVIDER_CHAIN),
                   help="Comma list of providers in order (google,mymemory,libre)")
    # New: allow forcing numeric mode
    p.add_argument("--no-menu", action="store_true",
                   help="Disable interactive space-bar menu and use numeric selection instead")
    return p.parse_args()

if __name__ == "__main__":
    args = parse_args()
    provider_chain = [x.strip().lower() for x in args.providers.split(",") if x.strip()]
    all_langs = load_json(LANG_FILE, required=True)
    # Default = space-bar menu; `--no-menu` forces numeric fallback
    selected_langs = prompt_language_selection(all_langs, no_menu=args.no_menu)
    generate_translations(selected_langs, provider_chain, max_retries=args.max_retries, zip_output=args.zip)
