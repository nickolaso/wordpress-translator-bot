# Wordpress Translator Bot #

## Setup

### Requirements
```
pip install polib python-dotenv colorama tqdm requests
pip install googletrans==4.0.0rc1 deep-translator
# Optional (for nice picker):
pip install InquirerPy
```

### Environment

``` .env ``` file

```
# Folder being searched for WordPress translations strings
SEARCH_DIR= 
# Name of the file being output
OUTPUT_FILE= 
# Location of the .pot file being used to create translations. .mo & .po files will be created in the same directory.
POT_FILE= 
```

### Creating a .pot file from a folder destination
```
SEARCH_DIR=<path-to-folder-to-translate> # absolute or relative path
OUTPUT_FILE=your-pot-file.pot
```

### For translating
```
POT_FILE=./your-pot-file.pot # absolute or relative path
```

### How to run
#### Create a .pot file
```
python create_pot.py
```
#### Create translations
```
python create_translations.py
```

### Arguments

- add --zip to archive the files at the end

### PowerShell (recommended)
```
python translate_bot.py --zip
```

### Git Bash / cmd
```
python translate_bot.py --zip
```

### Customize retries or provider order:
```
python translate_bot.py --max-retries 4 --providers google,mymemory,libre
```

### Languages & Data
- Add or remove what you need

```
languages.json
```
### Lists the languages you translated
```
{
  "ar": "Arabic",
  "zh-cn": "Chinese (Simplified)",
  "nl": "Dutch",
  "fr": "French",
  "de": "German",
  "el": "Greek",
  "he": "Hebrew",
  "it": "Italian",
  "ko": "Korean",
  "ne": "Nepali",
  "fa": "Persian",
  "pt": "Portuguese",
  "ru": "Russian",
  "es": "Spanish",
  "sv": "Swedish",
  "th": "Thai",
  "tr": "Turkish"
}

```

```
locale.json
```
#### - Maps the languages to locale for proper naming convention
```
{
  "ar": "ar_AR",
  "zh": "zh_CN",
  "zh-cn": "zh_CN",
  "zh-tw": "zh_TW",
  "nl": "nl_NL",
  "fr": "fr_FR",
  "de": "de_DE",
  "el": "el_GR",
  "he": "he_IL",
  "iw": "he_IL",
  "it": "it_IT",
  "ja": "ja_JP",
  "ko": "ko_KR",
  "ne": "ne_NP",
  "fa": "fa_IR",
  "pt": "pt_PT",
  "pt-br": "pt_BR",
  "ru": "ru_RU",
  "es": "es_ES",
  "es-mx": "es_MX",
  "sv": "sv_SE",
  "th": "th_TH",
  "tr": "tr_TR",
  "uk": "uk_UA",
  "pl": "pl_PL",
  "cs": "cs_CZ",
  "da": "da_DK",
  "fi": "fi_FI",
  "no": "nb_NO",
  "ro": "ro_RO",
  "hu": "hu_HU",
  "bn": "bn_BD",
  "hi": "hi_IN",
  "id": "id_ID",
  "ms": "ms_MY",
  "vi": "vi_VN"
}

```
### Output example
```
🚀 Starting translations for 17 languages...
📘 Input: ./test-plugin.pot
💾 Output folder: ./languages

🌍 Translating to French (fr)  →  locale fr_FR

🔹 Clock In
⠋ Trying google (attempt 1/3) → fr
✅ google → success
✅ → Horloge entrée

🔹 Clock Out
⠋ Trying google (attempt 1/3) → fr
❌ google failed: timeout
⚠️ retrying in 1s...
—
✅ google → success
✅ → Horloge sortie

💾 Saved ./languages/test-plugin-fr_FR.po
💾 Saved ./languages/test-plugin-fr_FR.mo

```