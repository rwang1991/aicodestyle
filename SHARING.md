# Sharing AIAnalyzer with your team

The fastest way for a non-developer teammate to use AIAnalyzer is to download a
zipped Windows bundle, unzip it anywhere (Desktop, OneDrive, USB stick), and
double-click `aianalyzer.exe`. The portal opens in their browser. No Python,
no `pip`, no venv. The exe scans **their** local AI sessions on **their**
machine — nothing leaves their box.

There are three paths depending on who you are sharing with.

---

## What gets scanned

AIAnalyzer reads session logs from these AI coding tools on the teammate's
machine:

| AI tool | Status | Where it reads from |
| --- | --- | --- |
| **GitHub Copilot CLI** | ✅ Supported | `~/.copilot/session-state/` |
| **VS Code — GitHub Copilot Chat** | ✅ Supported | `%APPDATA%\Code\User\workspaceStorage\**\chatSessions\*.json` (and `Code - Insiders`) |
| Visual Studio IDE — Copilot Chat | ❌ Not supported | Visual Studio does not persist chat history to disk in a parseable form — there is nothing to scan. |
| Claude Code | ❌ Not yet | Planned: `~/.claude/projects/**/*.jsonl` |
| Codex CLI | ❌ Not yet | Planned: `~/.codex/sessions/` |

The portal triggers a scan when the teammate clicks **Scan sessions**. If the
scan returns 0 sessions, the portal explains what it looked for and which
tools are supported, so the teammate isn't left guessing.

---

## A. Share with non-developers — the .exe bundle (recommended)

### 1. Build the bundle (once, on a Windows box with Python 3.11+)

```powershell
cd <repo-root>
.\packaging\build_exe.ps1
```

Output:
- `dist\aianalyzer\`   one-folder bundle (~115 MB, runs in place)
- `dist\aianalyzer.zip`   shareable archive (~50 MB)

You only need the `.zip`.

### 2. Ship the zip

Drop `aianalyzer.zip` in:
- Teams chat / channel,
- OneDrive / SharePoint share,
- internal file share,
- email (if your tenant allows 50 MB attachments).

### 3. What your teammate does

1. Save `aianalyzer.zip` somewhere they can write (Desktop is fine; do **not**
   leave it under `Downloads` on machines where Downloads is sandboxed).
2. Right-click → **Extract All…** (or unzip with 7-Zip).
3. Open the `aianalyzer` folder and double-click `aianalyzer.exe`.
4. A console window opens, prints `AIAnalyzer portal: http://127.0.0.1:8765/`,
   and the default browser opens to the portal automatically.
5. To stop, close the console window.

The first launch scans their AI sessions and may take 10–30 seconds before the
portal renders data.

### 4. Things to mention up front

- **Windows SmartScreen** may show "Windows protected your PC" the first time
  (unsigned binary). Click **More info → Run anyway**. This is expected for any
  internally-built exe that hasn't been code-signed.
- **Some antivirus** suites flag PyInstaller bundles as suspicious. If that
  happens, the binary is safe; the false positive comes from the PyInstaller
  bootloader. Whitelist the folder.
- **Corporate Application Control (WDAC / AppLocker)** can still block
  execution on locked-down machines. The bundle is built in one-folder mode
  (no `%TEMP%` extraction) specifically to minimise this, but if your org
  blocks unsigned exes entirely, see option C below.
- **Updating** is just: rebuild, reship the zip, teammate deletes the old
  folder and unzips the new one. Their session cache lives at
  `%LOCALAPPDATA%\AIAnalyzer\` and survives the swap.

---

## B. Share with developers — git + pip

If your teammate already has Python 3.11+ and `pip`:

```powershell
git clone <repo-url> aianalyzer
cd aianalyzer
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
aianalyzer serve
```

Or, once the repo lives at a stable URL, a one-liner via [pipx](https://pipx.pypa.io):

```powershell
pipx install git+<repo-url>
aianalyzer serve
```

This path tracks `main` and lets them pull updates with `git pull && pip install -e .`.

---

## C. Locked-down machines (last resort)

If WDAC blocks the bundled exe even in one-folder mode, the only reliable
paths are:

1. **Get the exe code-signed** with a corporate certificate, then redistribute
   the signed bundle.
2. **Have them install Python from the Microsoft Store** (which is
   pre-allow-listed in most orgs) and use option B.
3. **Run from WSL** — Python is unblocked in WSL on most managed Windows
   builds. Inside WSL: `pip install -e .` then `aianalyzer serve --host 0.0.0.0`
   and browse from Windows to `http://localhost:8765/`.

---

## What teammates will see

- Console window with one line: `AIAnalyzer portal: http://127.0.0.1:8765/`
- Browser tab opens to a single-page portal with:
  - Their archetype + a 2D quadrant map (Architect / Pilot / Tinkerer / Vibe Coder)
  - A 6-spoke behavior radar (Planner, Questioner, TODO-driver, Hands-on,
    Deliberator, Multi-tasker)
  - An AI-generated narrative profile (if a Copilot/Codex CLI is on PATH)
  - KPI cards, per-tool breakdown, session classification, behavior signals.
- A **Scan sessions** button at the top — they must click it once to populate
  the cache from their disk. If nothing is found (e.g., they only use
  Visual Studio IDE Copilot, which isn't supported), the portal shows a
  yellow banner explaining what was scanned and which tools are supported.

All processing is local. No telemetry, no upload.

---

## FAQ

**Q: Where is data stored?**
`%LOCALAPPDATA%\AIAnalyzer\` — cache database + ingested session features.
Safe to delete; AIAnalyzer rebuilds it on next launch.

**Q: How big is the download?**
~50 MB zipped, ~115 MB unzipped.

**Q: Does it need internet?**
No, unless the narrative-generation step is enabled and configured to use a
remote model. Scanning and the portal are fully offline.

**Q: Can I run it on macOS / Linux?**
The Python package works on both. The packaged `.exe` is Windows-only —
build a native bundle on each platform with PyInstaller using the same spec.
