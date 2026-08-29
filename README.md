<div align="center">

# 🐦 Colibri Converter

**Convert your Word and PDF documents without ever leaving your computer.**

No cloud. No account. No size limit. No data going who-knows-where.

[Download](#-installation) · [How it works](#-how-it-works) · [Actual fidelity](#-what-you-can-really-expect) · [Contribute](#-development)

</div>

---

## Why Colibri Converter

Online DOCX ↔ PDF converters all share an awkward trait: your document passes through their server. For a résumé, an invoice, a contract, an internal report — that isn't always acceptable.

Colibri Converter does the same thing, **entirely locally**. You drop a file onto the icon, and the result appears next to it a few seconds later. No outbound connection is ever made — you can turn off Wi-Fi and check for yourself.

- 🔒 **100% offline** — the document never leaves the machine
- 🖱️ **Drag and drop** — no command line to learn
- 📦 **Single file** — the executable is standalone, nothing to install
- 🖥️ **Windows & Linux** — macOS via the command line
- 📖 **Open source** — the code is fully readable, nothing hidden

---

## Installation

No external dependency: the DOCX ↔ PDF conversion is done entirely by Colibri Converter's own built-in engine. Nothing else to install.

### 🪟 Windows

1. **Download Colibri Converter** from the [Releases](../../releases) page: grab `colibri-converter-windows-x64.zip`.

2. **Unzip the archive** — right-click → *Extract All*. You get a single file, `colibri-converter.exe`. Put it wherever you want: Desktop, `Documents`, a USB drive — it's self-contained and doesn't depend on any neighboring folder.

3. **First launch**: double-click `colibri-converter.exe`.

   > Windows shows **SmartScreen** ("Windows protected your PC"): normal for an executable not signed with a paid certificate. Click *More info*, then *Run anyway*.
   >
   > Before that step, verify the integrity of the downloaded file. In PowerShell, from where the archive is:
   > ```powershell
   > Get-FileHash colibri-converter-windows-x64.zip
   > ```
   > The result must exactly match the `.sha256` file published alongside the archive on the Releases page.

4. Startup takes 2 to 5 seconds the first time — the executable extracts itself into a temporary folder (`%TEMP%`) before launching. This is normal, and faster on subsequent launches.

**Drag and drop**: once the exe is placed wherever you want, drag a `.docx` or `.pdf` file directly onto it to trigger the conversion without even opening the window.

> **Antivirus.** A "single-file" executable like this one structurally resembles what some malware does (self-extraction then launch) — this is a heuristic shared by Defender and third-party antivirus software, not a detection of actual malicious content. If yours flags it, you can verify the SHA-256 fingerprint above, check the (public) source code, or submit the file to [VirusTotal](https://www.virustotal.com/).

### 🐧 Linux

1. **Download** `colibri-converter-linux-x64.tar.gz` from the [Releases](../../releases) page, then unpack it:
   ```bash
   tar -xzf colibri-converter-linux-x64.tar.gz
   ```
   You get a single executable, `colibri-converter`.

2. **Make it executable** — the step Windows does automatically but Linux requires explicitly, as a security measure:
   ```bash
   chmod +x colibri-converter
   ```

3. **Launch it**:
   ```bash
   ./colibri-converter
   ```
   or double-click it from your file manager (Nautilus, Dolphin…) if graphical execution is enabled.

   Integrity check first, if you'd like:
   ```bash
   sha256sum colibri-converter-linux-x64.tar.gz
   ```
   to compare against the `.sha256` file published alongside the archive.

**Making the executable accessible from anywhere**, if you want to launch it without thinking about it:
```bash
mv colibri-converter ~/.local/bin/          # must be in your PATH
```
then launch `colibri-converter` from any terminal.

### 🍎 macOS

Not distributed as a binary: Gatekeeper blocks any non-notarized executable, and the workaround gets harder with every macOS version — shipping a non-notarized `.app` would be more frustrating than useful. Go through the command line instead:
```bash
git clone https://github.com/<you>/Colibri_Converter.git
cd Colibri_Converter
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
colibri-converter my_file.docx
```

---

## How it works

```
┌──────────────────────────────────────────────┐
│   Interface: drag and drop (PySide6)          │
│   or command line, for automation             │
├──────────────────────────────────────────────┤
│   Engine                                      │
│     • sanitization (macros, OLE removed)      │
│     • DOCX → PDF   via the built-in renderer  │
│       (render/, python-docx + ReportLab)      │
│     • PDF  → DOCX  via pdf2docx (+ OCR),      │
│       with a recovery pass for images         │
│       pdf2docx would otherwise drop           │
├──────────────────────────────────────────────┤
│   Fidelity audit (optional, --audit)          │
│     • text similarity                          │
│     • visual similarity, page by page          │
├──────────────────────────────────────────────┤
│   Isolated subprocesses, with timeout          │
│   and memory limit — both directions           │
└──────────────────────────────────────────────┘
```

**Why not LibreOffice (or WeasyPrint)?** Colibri Converter used to shell out to headless LibreOffice for DOCX → PDF. That meant one more program to install, and one more thing that could go missing or drift out of sync on the user's machine. The built-in renderer (`colibri_converter/render/`) removes that dependency entirely: it parses the `.docx` itself (python-docx, plus raw OOXML access for what python-docx doesn't expose — list numbering, section breaks, anchored images) and lays it out as a PDF with ReportLab. WeasyPrint was considered and rejected for the same reason LibreOffice was removed: it dynamically loads Pango/HarfBuzz/GObject/Fontconfig at runtime, a native system dependency by another name. ReportLab has no such requirement — only Pillow, itself pure enough to ship cleanly in a single-file executable — which is what keeps the "one binary, nothing to install" promise intact.

The trade-off is fidelity on the hardest documents: the built-in renderer covers paragraphs and character formatting, alignment/indentation, bulleted/numbered lists, simple and merged tables, inline images, headers/footers, page geometry and breaks, and hyperlinks — but multi-column sections, footnotes/endnotes, tracked changes and complex text-wrap-around-images aren't laid out yet. On any of these, the conversion still completes; it emits a `⚠` warning naming what was simplified rather than silently dropping it.

---

## What you can really expect

Document conversion isn't symmetric, and we'd rather tell you than let you find out with a mangled file.

| Direction | Fidelity | Why |
|---|:---:|---|
| **Word → PDF** | good on common documents | The built-in renderer covers text formatting, lists, tables, images, headers/footers and page geometry. Multi-column sections, footnotes, tracked changes and complex image text-wrap aren't laid out yet — the conversion still completes, with a `⚠` naming what was simplified, rather than failing or dropping content silently. |
| **PDF → Word** | 60–90% | An ordinary PDF contains no paragraphs or styles — only glyphs positioned on a page. Reconstruction is exactly that: a reconstruction, not a reading. |
| **Scanned PDF → Word** | variable | No native text: quality depends entirely on the scan and the OCR. Proofreading always recommended. |

On a simple text document, PDF → Word conversion is generally excellent. On a multi-column layout with nested tables or footnotes, expect some touch-up.

We'd rather under-promise here than publish an invented number: the honest way to know the fidelity on *your* documents is the `--audit`/`roundtrip_audit()` mechanism below, run on a corpus that looks like what you actually convert.

**Rather than leaving you to guess**, the application can measure the gap between the original file and the result itself:

```bash
colibri-converter report.pdf --audit
```

```
Verdict: COMPLIANT
  Text fidelity: 97.40%
  Pages: 12 -> 12
```

A low score doesn't mean the tool did a poor job — often, it means the source PDF simply didn't contain the information needed to reconstruct a faithful document. The score exists to tell you that *before* you send it to someone.

---

## Command line

For automation, scripts, or simply if you prefer it:

```bash
# A single file
colibri-converter report.docx -o ./output

# An entire folder, in parallel
colibri-converter ./documents -o ./output -j 4

# With a fidelity check and a blocking threshold (useful in CI)
colibri-converter ./corpus -o ./output --audit --fail-under 0.95

# Scanned PDF, forced OCR
colibri-converter scan.pdf -o ./output --ocr always --ocr-lang eng

# Long-term archiving (PDF/A)
colibri-converter contract.docx -o ./output --pdfa
```

As a Python library:

```python
from colibri_converter import convert, audit

result = convert("report.docx", "report.pdf", pdfa=True)
print(result.warnings)
print(audit("report.docx", "report.pdf").summary())
```

---

## Security

A converter, by definition, receives files of unknown origin. Colibri Converter assumes **the input document is hostile**:

- VBA macros, ActiveX and OLE objects removed before any rendering
- protection against zip bombs and zip-slip (a DOCX is a ZIP archive)
- neutralization of relationships pointing to a remote external target (remote templates, network callbacks) — locally linked media is preserved
- both conversion directions confined to an isolated process, with a memory limit and a timeout
- the (optional) OCR binary resolution is hardened against path hijacking

Full details, acknowledged limitations and reporting procedure: **[SECURITY.md](SECURITY.md)**

---

## Development

```bash
git clone https://github.com/<you>/Colibri_Converter.git
cd Colibri_Converter
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pytest -v                    # full suite, no external dependency needed
```

Building the executable:

```bash
python tools/make_icons.py
pyinstaller --noconfirm --clean colibri-converter.spec
```

By default, the build produces a **single-file executable** (`ONEFILE=1`, the default value). To fall back to a classic folder build — instant startup, but not movable outside its folder:

```bash
ONEFILE=0 pyinstaller --noconfirm --clean colibri-converter.spec
```

Architecture, technical choices and already-solved packaging pitfalls: see the comments in `colibri_converter/engine.py` and the CI (`.github/workflows/release.yml`), which builds and tests on Windows and Linux before every release.

---

## License

**AGPL-3.0-or-later** — inherited from PyMuPDF and pdf2docx, on which the PDF → Word conversion relies. Details and implications: **[LICENSE.md](LICENSE.md)**.

<div align="center">

*Made with a vector hummingbird, to avoid any copyright issues.*

</div>
