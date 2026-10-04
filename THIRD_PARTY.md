# Third-party components

Mucify itself is licensed under **GPL-3.0-or-later** (see [LICENSE](LICENSE)). It bundles or uses the
components below, each under its own licence. The exact texts ship in the installer's `licenses` folder
and in the repository's `tools/` folder.

## Programs shipped inside the installer

| Component | Role | Licence | Source |
|---|---|---|---|
| **sldl** 2.6.0 (now developed as *Sockseek*, formerly slsk-batchdl) | Soulseek downloader, run as a separate program by Mucify | **GNU AGPL-3.0** (`tools/sldl/LICENSE.txt`) | <https://github.com/fiso64/sockseek> |
| **rsgain** 3.7 | ReplayGain 2.0 tagger, run as a separate program | **BSD 2-Clause** (`tools/rsgain/LICENSE.txt`); contains CRC++ under its own BSD licence (`tools/rsgain/LICENSE-CRCpp.txt`) | <https://github.com/complexlogic/rsgain> |
| Microsoft Visual C++ runtime DLLs (`vcruntime140.dll`, `vcruntime140_1.dll`, `msvcp140.dll`) | Needed by rsgain | Microsoft redistributable terms | <https://learn.microsoft.com/cpp/windows/redistributing-visual-cpp-files> |
| **Python** runtime | Runs Mucify | PSF-2.0 | <https://www.python.org> |
| **Flask**, Werkzeug, Jinja2, MarkupSafe, itsdangerous, click, blinker | Local web service for the interface | BSD-3-Clause (blinker: MIT) | <https://palletsprojects.com> |
| **Requests** (and urllib3, idna, charset-normalizer, certifi) | Qobuz look-ups | Apache-2.0 (urllib3 and charset-normalizer: MIT, idna: BSD-3-Clause, certifi: MPL-2.0) | <https://requests.readthedocs.io> |
| **Mutagen** | Audio tag handling | **GPL-2.0-or-later** | <https://github.com/quodlibet/mutagen> |
| **pywebview** (with pythonnet, clr-loader, bottle, proxy_tools) | Native window | BSD-3-Clause (pythonnet, clr-loader, bottle: MIT) | <https://pywebview.flowrl.com> |
| **PyInstaller** bootloader | Starts the packaged app | GPL-2.0-or-later *with the bootloader exception* that lets the produced program use any licence | <https://pyinstaller.org> |
| **Microsoft Edge WebView2** runtime | Draws the window (installed from Microsoft if missing) | Microsoft Software License Terms | <https://developer.microsoft.com/microsoft-edge/webview2> |

The installer also contains an automatically generated list of **every** Python package in the build with
its licence text: `licenses\python-packages.txt`.

## How the licences fit together
- **Mucify + Mutagen.** Mutagen is GPL-2.0-or-later and is bundled inside Mucify, so Mucify as a whole is
  distributed under **GPL-3.0-or-later**, which is compatible with Mutagen's "or later" terms. That is the
  reason Mucify cannot use a more permissive licence such as MIT.
- **sldl (AGPL-3.0).** `sldl.exe` is a separate program that Mucify starts as its own process and talks to
  through its command line. It is shipped unmodified, unlike Mucify's own code. It is passed on under the AGPL-3.0,
  and its licence text is included. The complete corresponding source code of the shipped version is available from the
  upstream project linked above (release 2.6.0, see `tools/sldl/VERSION.txt`). If that link ever becomes
  unavailable, open an issue and the source will be provided.
- **rsgain (BSD-2-Clause).** Its copyright notices are kept in `tools/rsgain/LICENSE.txt`:
  Copyright (c) 2014 Alessandro Ghedini; v0.1-v0.6.8 Copyright (C) 2019 Matthias C. Hormann; rsgain by complexlogic, 2022.
- **Installer tooling.** Inno Setup is used only to build the installer; its licence places no restrictions on
  the installers it produces.

## Updating the bundled tools
Replacing `sldl.exe` or `rsgain.exe` is a deliberate manual step. When you do, update the version in
`tools/sldl/VERSION.txt` (or the rsgain folder name) and this file.
