# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

GOE메신저 추출기 — a Windows desktop app that reads the local SQLite database used by the GOE Messenger (AtMessenger / GOEMessenger) client, decrypts it if necessary, and exports messages as CSV bundles. The UI is customtkinter, Korean throughout. All comments, log output, and UI strings are Korean by convention.

## Commands

There is no package manager file in the repo. Install dependencies directly:

```bash
pip install customtkinter pycryptodome Pillow
python goe_extractor.py          # launch the app
python make_logo.py               # regenerate the 1080x1080 store logo PNG
```

Build the distributable EXE + installer (Windows only, requires PyInstaller and Inno Setup):

```bash
pyinstaller --onefile --noconsole --name "GOE메신저추출기" goe_extractor.py
ISCC.exe installer.iss            # produces installer_output\GOE메신저추출기_Setup_<ver>.exe
```

The app targets Windows specifically — it uses `os.startfile`, reads `%LOCALAPPDATA%` / `%APPDATA%`, and the installer is Inno Setup. There are no tests, no linter config, and no CI.

## Architecture

Single-file application: `goe_extractor.py` (~1250 lines) with two cleanly separated layers followed by the Tk GUI.

### Layer 1 — Decryption (`decrypt_db`)

GOE Messenger ships DB files in two forms. Files starting with the `SQLite format 3\x00` magic are already plain SQLite and are returned as-is. Otherwise the file is a SQLCipher-style encrypted DB and is decrypted in-memory with these fixed parameters:

- Page size `1024`, reserve `48`, salt `16` bytes at the start of the file.
- Key: `PBKDF2-HMAC-SHA1(password=b"49100hsy", salt=first 16 bytes, iter=64000, dklen=32)`.
- Per page: `AES-CBC` with IV at `page[PAGE_SIZE - RESERVE:PAGE_SIZE - RESERVE + 16]`. The first page skips the salt bytes and is re-prefixed with the SQLite header.

The decrypted output is written to a `tempfile.NamedTemporaryFile(suffix=".db", delete=False)` and `DBReader.close()` `os.unlink`s it. If you change the decryption code, keep that cleanup path intact — the temp file holds cleartext message data.

### Layer 2 — DB access (`DBReader`)

Wraps `sqlite3` and handles schema drift across GOE Messenger versions by probing `sqlite_master`:

- Messages: `tblMessage` (sender/receiver, `sDate` as `YYYYMMDDHHMMSS` strings, `cIsSend == 'Y'` means outbound).
- Chat content: `tblChatContent` or `tblChatMessage` (fallback) — `_ct()` picks whichever exists.
- Chat rooms: `tblChatRoomInfo` or `tblChatRoom` — `_rt()` picks whichever exists.

`_dw(df, dt, depts)` builds a shared `WHERE` clause for date range + optional department filter used by `counts`, `departments`, `senders`, `receivers`, and `notes`. Date filters interpolate `YYYYMMDD000000` / `YYYYMMDD235959` to match the `sDate` string format. Any new query that takes user-driven filters should reuse `_dw` rather than concatenating SQL directly.

`clean_content` strips `{RTF}`-tagged payload tails that some messages carry.

### Layer 3 — GUI (`App` / customtkinter)

Single `ctk.CTk` window built in `_build` with a fixed colour palette in the module-level `C` dict. Notable flows:

- `_auto_detect` runs 300 ms after launch; `find_talk_db()` scans `DB_SEARCH_PATHS` (LOCALAPPDATA/APPDATA under `AtMessenger`, `AtMessenger7`, `GOEMessenger`) for `@Talk.db`, `Talk.db`, or any `*.db`, sorted by size.
- `_refresh_stats` computes both the unfiltered ("전체") and department-filtered ("표시") counts, updates five stat labels, and triggers `_flash_stats` for a red → orange → neutral animation when any value changes.
- Department filter: `_populate_depts` renders a checkbox list. `_get_selected_depts()` returns `None` when every box is checked (meaning "no filter"), otherwise the explicit list — callers must treat `None` as "all" rather than "none".
- All `_export_*` methods funnel through `_run_export` → `_safe_export` which runs the work on a daemon thread and marshals UI updates back with `self.after(0, ...)`. The `self.processing` flag guards against concurrent exports. CSV output uses `utf-8-sig` (BOM) so Excel opens Korean correctly.

### Installer

`installer.iss` is an Inno Setup script that packages `dist\GOE메신저추출기.exe` (the PyInstaller output). Version is defined in `#define MyAppVersion`; bump it there and in `APP_VERSION` in `goe_extractor.py` together.

## Conventions

- Korean-only for UI strings, log messages, export filenames, and commit messages.
- Keep the two schema probes (`_ct`, `_rt`) and don't hardcode table names elsewhere — older DBs are still in the wild.
- Never log or write the decryption password or key material; treat the temp decrypted file as sensitive and always unlink via `DBReader.close()`.
- Long-running work (decryption, export) must not block the Tk main loop — use the `_run_export` helper and `self.after` to post back to the UI thread.
