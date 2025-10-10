import os
import re
import sys
import time
import itertools
import polib
from tqdm import tqdm
from dotenv import load_dotenv
from colorama import Fore, Style, init

# ================================================================
# 🧩 UTF-8 Safety
# ================================================================
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

# ================================================================
# 💻 Terminal Setup
# ================================================================
init(autoreset=True)
load_dotenv()

SEARCH_DIR = os.path.abspath(os.path.normpath(os.getenv("SEARCH_DIR", "./").strip().strip('"').strip("'")))
OUTPUT_FILE = os.path.abspath(os.path.normpath(os.getenv("OUTPUT_FILE", "translations.pot")))
ENCODING = "utf-8"

# ================================================================
# 🎨 Helpers
# ================================================================
def emoji(symbol: str, fallback: str) -> str:
    """Safe emoji output with fallback for limited terminals."""
    try:
        return symbol if sys.stdout.encoding and sys.stdout.encoding.lower().startswith("utf") else fallback
    except Exception:
        return fallback

def info(msg):  print(f"{Fore.CYAN}{emoji('ℹ️','[i]')}{Style.RESET_ALL} {msg}")
def ok(msg):    print(f"{Fore.GREEN}{emoji('✅','[OK]')}{Style.RESET_ALL} {msg}")
def warn(msg):  print(f"{Fore.YELLOW}{emoji('⚠️','[!]')}{Style.RESET_ALL} {msg}")
def err(msg):   print(f"{Fore.RED}{emoji('❌','[X]')}{Style.RESET_ALL} {msg}")

# ================================================================
# 🔍 Plugin Header
# ================================================================
PLUGIN_HEADER_RE = re.compile(r'^[\s*/#@-]*Plugin\s+Name\s*:\s*(?P<name>.+?)\s*$', re.I | re.M)
plugin_main_file = None

def find_plugin_name(base_dir):
    for root, _, files in os.walk(base_dir):
        for f in files:
            if f.lower().endswith(".php"):
                try:
                    with open(os.path.join(root, f), "r", encoding="utf-8", errors="ignore") as fh:
                        text = fh.read(20000)
                        m = PLUGIN_HEADER_RE.search(text)
                        plugin_main_file = f.lower()
                        if m:
                            return m.group("name").strip()
                except Exception:
                    pass
    return "Unknown Plugin"

# ================================================================
# 🧠 WordPress gettext pattern (Poedit-level)
# ================================================================
# Matches ALL standard gettext functions (and their esc_ variants)
# and allows variables like $this->text_domain. Uses lazy matching.
GETTEXT_FUNC_RE = re.compile(
    r'''(?x)
    (?:printf|sprintf)?\s*\(?        # optional printf/sprintf(
    (?P<func>__|_e|_x|_ex|_n|_nx|esc_html__|esc_html_e|esc_html_x|esc_attr__|esc_attr_e|esc_attr_x)
    \s*\(                             # the opening parenthesis of gettext call
    ''',
    re.IGNORECASE
)

# string literal matcher used inside the parsed call argument body
STRING_RE = re.compile(r"""(['"])(?P<str>(?:\\.|(?!\1).)*?)\1""", re.DOTALL)

def normalize_php_string(s: str) -> str:
    """Clean escaped quotes and slashes from PHP string literals."""
    if not s:
        return s
    # Order matters: unescape backslashes last
    s = s.replace("\\'", "'").replace('\\"', '"')
    s = s.replace('\\\\', '\\')
    return s.replace("\r", "").replace("\n", "").strip()

def extract_strings(content: str):
    """
    Phase 1: find gettext functions.
    Phase 2: manually grab their argument slice (balanced parentheses) and parse string literals.
    """
    results = []
    for m in GETTEXT_FUNC_RE.finditer(content):
        func = m.group('func')
        start = m.end()  # position right after '(' of the gettext call
        depth = 1
        end = start
        while end < len(content) and depth > 0:
            ch = content[end]
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
            end += 1
        call_body = content[start:end-1]  # inside gettext(...)
        # collect literal arguments only; domain may be a variable and will be ignored
        parts = [normalize_php_string(s.group('str')) for s in STRING_RE.finditer(call_body)]

        # map args to expected positions based on function type
        msgid = parts[0] if parts else ""
        msgid2 = parts[1] if len(parts) > 1 else None
        context = parts[2] if len(parts) > 2 else None

        plural = msgid2 if func.lower() in ("_n", "_nx") else None
        ctx = context if func.lower() in ("_x", "_ex", "_nx", "esc_html_x", "esc_attr_x") else None

        results.append({
            "func": func,
            "msgid": msgid,
            "plural": plural,
            "context": ctx,
            "pos": m.start()
        })
    return results

# ================================================================
# 🔍 Recursive PHP File Finder
# ================================================================
def find_php_files(base_dir):
    exclude = {'.git', 'vendor', 'node_modules', '__pycache__', 'build', 'dist'}
    for root, dirs, files in os.walk(base_dir, topdown=True):
        dirs[:] = [d for d in dirs if d.lower() not in exclude]
        for f in files:
            if f.lower().endswith(".php"):
                yield os.path.join(root, f)

def compute_line(content, pos): return content.count("\n", 0, pos) + 1
def relpath(p): return os.path.relpath(p, SEARCH_DIR).replace("\\", "/")

# ================================================================
# 🚀 Main Extraction Logic
# ================================================================
def generate_pot():
    print(f"\n{emoji('🌍','')} {Fore.CYAN}{Style.BRIGHT}WordPress Translation Extractor{Style.RESET_ALL}")
    info(f"Scanning directory: {SEARCH_DIR}")

    plugin_name = find_plugin_name(SEARCH_DIR)
    info(f"Plugin name detected: {plugin_name}")

    php_files = list(find_php_files(SEARCH_DIR))
    if not php_files:
        warn("No PHP files found!")
        return

    entries = {}
    for path in tqdm(php_files, desc="Parsing PHP", ncols=100):
        try:
            with open(path, "r", encoding=ENCODING, errors="ignore") as f:
                content = f.read()
        except Exception as e:
            warn(f"Skipping {path}: {e}")
            continue

        for it in extract_strings(content):
            line = compute_line(content, it["pos"])
            key = (it["context"], it["msgid"], it["plural"])
            entries.setdefault(key, []).append((relpath(path), line))
            print(f"{Fore.GREEN}+ {relpath(path)}:{line}{Style.RESET_ALL} → {it['msgid']}")

    # Build POT
    pot = polib.POFile()
    pot.metadata = {
        "Project-Id-Version": plugin_name,
        "Report-Msgid-Bugs-To": plugin_name,
        "POT-Creation-Date": time.strftime("%Y-%m-%d %H:%M%z"),
        "PO-Revision-Date": time.strftime("%Y-%m-%d %H:%M%z"),
        "Last-Translator": "",
        "Language-Team": "",
        "MIME-Version": "1.0",
        "Content-Type": "text/plain; charset=UTF-8",
        "Content-Transfer-Encoding": "8bit",
        "Plural-Forms": "nplurals=2; plural=(n != 1);",
    }

    for (ctx, msgid, plural), occs in sorted(entries.items(), key=lambda x: x[0][1].lower()):
        entry = polib.POEntry(
            msgid=msgid,
            msgstr="",
            occurrences=[(p, int(l)) for (p, l) in occs]
        )
        if plural:
            entry.msgid_plural = plural
        if ctx:
            entry.msgctxt = ctx
        if entry.msgctxt != "":
            pot.append(entry)

    pot.save(OUTPUT_FILE)
    ok(f"POT file generated → {OUTPUT_FILE}")
    info(f"Files scanned: {len(php_files)}")
    info(f"Unique strings: {len(entries)}")

    # ================================================================
    # 🧾  Summary Table and Status Bar (Enhanced, Color-Coded)
    # ================================================================
    total_strings = sum(len(v) for v in entries.values())
    unique_strings = len(entries)

    print()
    print(f"{Fore.CYAN}{'═'*60}")
    print(f"{Fore.WHITE}{emoji('📊','[Stats]')}  Extraction Summary".center(60))
    print(f"{Fore.CYAN}{'═'*60}{Style.RESET_ALL}")

    print(f"{Fore.YELLOW}{emoji('📦','[Files]')}  Files scanned:{Style.RESET_ALL} {len(php_files)}")
    print(f"{Fore.YELLOW}{emoji('💬','[Strings]')}  Total strings found:{Style.RESET_ALL} {total_strings}")
    print(f"{Fore.YELLOW}{emoji('🧩','[Unique]')}  Unique msgids:{Style.RESET_ALL} {unique_strings}")
    print(f"{Fore.YELLOW}{emoji('📛','[Plugin]')}  Plugin name:{Style.RESET_ALL} {plugin_name}")
    print(f"{Fore.YELLOW}{emoji('📂','[Path]')}  Output file:{Style.RESET_ALL} {OUTPUT_FILE}\n")

    # 🔁 Duplicate Summary
    from collections import Counter
    dupes = Counter([k[1] for k in entries.keys()])
    duplicates = {k: v for k, v in dupes.items() if v > 1}

    if duplicates:
        print(f"{Fore.MAGENTA}{emoji('🔁','[Dupes]')}  Duplicate strings detected:{Style.RESET_ALL}\n")
        print(f"{Fore.LIGHTBLACK_EX}{'Message ID':40} Count{Style.RESET_ALL}")
        print(f"{Fore.LIGHTBLACK_EX}{'-'*50}{Style.RESET_ALL}")
        for msgid, count in sorted(duplicates.items(), key=lambda x: -x[1])[:10]:
            short = (msgid[:37] + '...') if len(msgid) > 40 else msgid
            if count <= 2:
                c = Fore.GREEN
            elif count <= 5:
                c = Fore.YELLOW
            else:
                c = Fore.RED
            print(f"{Fore.WHITE}{short:40} {c}{count}{Style.RESET_ALL}")
        print()
    else:
        print(f"{Fore.GREEN}{emoji('✨','[OK]')}  No duplicates found!{Style.RESET_ALL}\n")

    # 🧭 Animated non-flicker status bar at the bottom
    spinner = itertools.cycle(['⠋','⠙','⠹','⠸','⠼','⠴','⠦','⠧','⠇','⠏'])
    print(f"{Fore.CYAN}Finalizing POT file...{Style.RESET_ALL}", end="", flush=True)
    for _ in range(20):
        sys.stdout.write(f"\r{Fore.CYAN}{next(spinner)} Finalizing POT file...{Style.RESET_ALL}")
        sys.stdout.flush()
        time.sleep(0.05)
    print(f"\r{Fore.GREEN}✅  POT file finalized successfully!{' '*20}{Style.RESET_ALL}\n")

    print(f"{Fore.GREEN}{'=' * 60}")
    print(f"✨  Extraction complete! Ready to Translate 🎉")
    print(f"{'=' * 60}{Style.RESET_ALL}\n")

# ================================================================
if __name__ == "__main__":
    try:
        generate_pot()
    except Exception as e:
        err(f"Error: {e}")
