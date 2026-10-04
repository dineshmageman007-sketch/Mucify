# Developing Mucify

## Build (GitHub Actions)
Push the repository to GitHub. The workflow in `.github/workflows/build-windows.yml` runs on every push / PR / manual dispatch:

`tests → PyInstaller (dist\Mucify\Mucify.exe) → packaged-app self-test → Inno Setup installer`

Download **Mucify-Setup-x.y.z** (and a portable zip) from the run's *Artifacts*. Pushing a tag like `v1.0.1` also attaches both files to a GitHub Release and uses the tag as the version.

## Build locally (Windows, Python 3.11 x64, Inno Setup 6)
```powershell
./build.ps1              # tests, exe, self-test, installer -> installer\Output\
./build.ps1 -SkipInstaller
```
Run from source for development: `pip install -r requirements.txt` then `python -m mucify` (needs Windows + WebView2 for the window).

## Layout
| Path | Purpose |
|---|---|
| `mucify/app.py` | Flask backend: the original pipeline plus first-run, Soulseek test, Qobuz connect endpoints |
| `mucify/main.py` | Desktop launcher (private local server + native pywebview window), `--selftest` for CI |
| `mucify/qobuz_auth.py` | In-app Qobuz login window + token capture (`PROBE_JS`) |
| `mucify/soulseek.py` | Random credentials + direct Soulseek login test |
| `mucify/paths.py` | AppData / Music folders, bundled-tool staging |
| `tools/sldl`, `tools/rsgain` | **Tested** binaries shipped as-is. Never auto-updated; Mucify never downloads tools |
| `mucify.spec`, `build.ps1`, `installer/mucify.iss` | Packaging |
| `tests/` | `python -m unittest discover -s tests -t .` (or `pytest`) |

## Updating the bundled tools (deliberate, manual)
Replace the files under `tools/` yourself after re-testing the pipeline with the new version, then push. Mucify copies `sldl.exe` into `%APPDATA%\Mucify\tools\sldl` on first run (it needs a writable folder for `sldl.conf`) and refreshes that copy when the app version or file size changes.

## If automatic Qobuz detection stops working
Only `PROBE_JS` and `_candidates()` in `mucify/qobuz_auth.py` need changing (where the web player keeps the token), plus `validate_token()` if Qobuz changes the check endpoint. The manual-token path is independent of both. `tests/probe_sim.js` simulates the probe in Node.

## Security notes
- **Never commit `sldl.conf` or any file containing your Soulseek login.** Mucify writes it at runtime to `%APPDATA%`; the repo's `.gitignore` excludes it.
- The local backend only accepts requests from Mucify's own window (Host check + required header).
- Third-party licences: see `THIRD_PARTY.md`. Security reports: see `SECURITY.md`.


---


## Window, music and Guide pieces
| Path | Purpose |
|---|---|
| `mucify/winstate.py` | Remembers maximized/windowed state, size and position (Win32); F11 fullscreen is never saved |
| `mucify/audiometa.py` | Dependency-free MP3/FLAC tag + cover reader for the sidebar mini player |
| `mucify/reset.py` | Reset / uninstall (allow-listed clean-up helper) |
| `mucify/projects.py` | Per-playlist folders and the "last file" cards |
