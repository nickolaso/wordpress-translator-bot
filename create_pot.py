import os
import re
import sys
import time
import polib
from tqdm import tqdm
from dotenv import load_dotenv
from colorama import Fore, Style, init

# ================================================================
# 🧩 ENCODING FIXES — prevent cp1252 / UnicodeEncodeError
# ================================================================
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

# ================================================================
# 💻 Terminal Capability Detection
# ================================================================
def detect_terminal():
    shell = os.environ.get("SHELL", "") or os.environ.get("ComSpec", "")
    s = shell.lower()
    if "git" in s:
        return "gitbash"
    if "bash" in s:
        return "bash"
    if "powershell" in s:
        return "powershell"
    if "cmd" in s or "cmd.exe" in s:
        return "cmd"
    return "unknown"

TERM = detect_terminal()
IS_WINDOWS = os.name == "nt"

USE_EMOJIS = (
    sys.stdout.encoding
    and sys.stdout.encoding.lower().startswith("utf")
    and TERM not in ["cmd", "gitbash", "powershell"]
)
TQDM_SIMPLE = TERM in ["cmd", "gitbash"]

init(autoreset=True, strip=not sys.stdout.isatty())

# ================================================================
# 🎨 Logging Helpers
# ================================================================
def emoji(symbol, fallback):
    return symbol if USE_EMOJIS else fallback

def colorize(text, color):
    if not sys.stdout.isatty():
        return text
    try:
        return f"{color}{text}{Style.RESET_ALL}"
    except Exception:
        return text

def info(msg):  print(f"{colorize(emoji('ℹ️ ', '[i] '), Fore.CYAN)}{msg}")
def ok(msg):    print(f"{colorize(emoji('✅', '[OK]'), Fore.GREEN)} {msg}")
def warn(msg):  print(f"{colorize(emoji('⚠️ ', '[!] '), Fore.YELLOW)}{msg}")
def err(msg):   print(f"{colorize(emoji('❌', '[X] '), Fore.RED)}{msg}")
def step(msg):  print(f"{colorize(emoji('⚙️ ', '[-] '), Fore.MAGENTA)}{msg}")

# ================================================================
# ⚙️ Configuration
# ================================================================
load_dotenv()

SEARCH_DIR   = os.getenv("SEARCH_DIR", "./").rstrip("/\\")
OUTPUT_FILE  = os.getenv("OUTPUT_FILE", "translations.pot")
ENCODING     = "utf-8"

# ================================================================
# 🧩 Normalization Fix — remove PHP escape sequences
# ================================================================
def normalize_php_string(s: str) -> str:
    """Convert PHP-escaped strings to real text for clean .pot output."""
    if not s:
        return s
    s = s.replace("\\'", "'").replace('\\"', '"').replace('\\\\', '\\')
    return s

# ================================================================
# 🧠 Regex Patterns for WP gettext functions
# ================================================================
STRING = r"""(?P<{name}_q>['"])(?P<{name}>(?:\\.|(?! (?P={name}_q)).)*?)(?P={name}_q)"""
def build(p): return re.compile(p, re.VERBOSE | re.DOTALL)

PATTERNS = [
    build(rf"""(?P<func>__|_e|esc_html__|esc_html_e|esc_attr__|esc_attr_e)\(
        \s*{STRING.format(name='msgid')}
        (?:\s*,\s*{STRING.format(name='domain')})?
    \)"""),
    build(rf"""(?P<func>_x|_ex|esc_html_x|esc_attr_x)\(
        \s*{STRING.format(name='msgid')}
        \s*,\s*{STRING.format(name='context')}
        (?:\s*,\s*{STRING.format(name='domain')})?
    \)"""),
    build(rf"""(?P<func>_n)\(
        \s*{STRING.format(name='sing')}
        \s*,\s*{STRING.format(name='plur')}
        \s*,\s*[^,)\s]+
        (?:\s*,\s*{STRING.format(name='domain')})?
    \)"""),
    build(rf"""(?P<func>_nx)\(
        \s*{STRING.format(name='sing')}
        \s*,\s*{STRING.format(name='plur')}
        \s*,\s*[^,)\s]+
        \s*,\s*{STRING.format(name='context')}
        (?:\s*,\s*{STRING.format(name='domain')})?
    \)"""),
]

def relpath(p): return os.path.relpath(p, SEARCH_DIR).replace("\\", "/")

# ================================================================
# 🔍 Extraction Helpers
# ================================================================
def find_php_files(base_dir):
    for root, dirs, files in os.walk(base_dir):
        dirs[:] = [d for d in dirs if d not in ('.git', 'node_modules', 'vendor', 'dist', 'build')]
        for f in files:
            if f.endswith(".php"):
                yield os.path.join(root, f)

def compute_line(content, pos):
    return content.count("\n", 0, pos) + 1

def extract(content):
    found = []
    for pat in PATTERNS:
        for m in pat.finditer(content):
            gd = m.groupdict()
            if 'sing' in gd:  # plural
                found.append({
                    "msgid": normalize_php_string(gd.get('sing')),
                    "plural": normalize_php_string(gd.get('plur')),
                    "context": normalize_php_string(gd.get('context')),
                    "pos": m.start()
                })
            else:
                found.append({
                    "msgid": normalize_php_string(gd.get('msgid')),
                    "plural": None,
                    "context": normalize_php_string(gd.get('context')),
                    "pos": m.start()
                })
    return found

# ================================================================
# 🚀 Main Logic
# ================================================================
def generate_pot():
    print(f"\n{Fore.BLUE}{Style.BRIGHT}{emoji('🌍', '')} WordPress Translation Extractor{Style.RESET_ALL}")
    print(f"{Fore.WHITE}--------------------------------------------------{Style.RESET_ALL}")
    print(f"📁 Directory: {Fore.YELLOW}{SEARCH_DIR}{Style.RESET_ALL}")
    print(f"🗂️  Output file: {Fore.YELLOW}{OUTPUT_FILE}{Style.RESET_ALL}\n")

    php_files = list(find_php_files(SEARCH_DIR))
    if not php_files:
        warn("No PHP files found. Check SEARCH_DIR.")
        return

    step("Scanning PHP files...\n")
    entries_map = {}

    for path in tqdm(php_files, desc="Processing files", ncols=100, disable=TQDM_SIMPLE):
        rel = relpath(path)
        try:
            with open(path, "r", encoding=ENCODING, errors="ignore") as f:
                content = f.read()
        except Exception as e:
            warn(f"Skipping {rel}: {e}")
            continue

        for it in extract(content):
            line = compute_line(content, it['pos'])
            key = (it['context'], it['msgid'], it['plural'])
            entries_map.setdefault(key, []).append((rel, line))
            # Live line-by-line logging
            print(f"{Fore.GREEN if sys.stdout.isatty() else ''}+ {rel}:{line}{Style.RESET_ALL} → {it['msgid']}")

    # Build POT file
    pot = polib.POFile()
    pot.metadata = {
        "Project-Id-Version": "1.0",
        "Report-Msgid-Bugs-To": "",
        "POT-Creation-Date": time.strftime("%Y-%m-%d %H:%M%z"),
        "PO-Revision-Date": "",
        "Last-Translator": "",
        "Language-Team": "",
        "MIME-Version": "1.0",
        "Content-Type": "text/plain; charset=UTF-8",
        "Content-Transfer-Encoding": "8bit",
    }

    for (ctx, msgid, plural), occs in sorted(entries_map.items(), key=lambda x: x[0][1].lower()):
        entry = polib.POEntry(
            msgid=msgid,
            msgstr="",
            occurrences=[(p, int(ln)) for (p, ln) in occs]
        )
        if plural:
            entry.msgid_plural = plural
        if ctx:
            entry.msgctxt = ctx
        pot.append(entry)

    pot.save(OUTPUT_FILE)

    ok(f"POT file generated → {OUTPUT_FILE}")
    info(f"📂 Files scanned: {len(php_files)}")
    info(f"💬 Unique strings: {len(entries_map)}")

    print(f"{Fore.GREEN}{'=' * 60}")
    print(f"✨  Extraction complete! Ready for localization 🎉")
    print(f"{'=' * 60}{Style.RESET_ALL}\n")

# ================================================================
if __name__ == "__main__":
    try:
        generate_pot()
    except Exception as e:
        err(f"Error: {e}")
