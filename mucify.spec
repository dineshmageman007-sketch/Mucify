# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Mucify.  Build with:  pyinstaller --noconfirm --clean mucify.spec
# Output: dist/Mucify/Mucify.exe (onedir, windowed, no console)
import os
from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(SPECPATH)


def tree(src_rel, dest, skip_ext=()):
    """(source, dest-folder) pairs for every file under src_rel, keeping the layout."""
    out = []
    base = os.path.join(ROOT, src_rel)
    for dirpath, _dirs, files in os.walk(base):
        for f in files:
            if f.lower().endswith(tuple(skip_ext)):
                continue
            rel = os.path.relpath(dirpath, base)
            out.append((os.path.join(dirpath, f), os.path.normpath(os.path.join(dest, rel))))
    return out


datas = []
datas += tree("mucify/templates", "mucify/templates")
datas += tree("mucify/static", "mucify/static")
datas += tree("assets", "assets", skip_ext=(".bmp", "-1024.png"))          # installer-only images stay out
# The tested sldl.exe / rsgain.exe (+ their DLLs, presets, licenses). Debug symbols are not needed.
datas += tree("tools", "tools", skip_ext=(".pdb",))
# License, credits and legal notices (shown in Settings > About & legal)
for _doc in ("LICENSE", "THIRD_PARTY.md", "DISCLAIMER.md", "PRIVACY.md", "CREDITS.md"):
    datas.append((os.path.join(ROOT, _doc), "legal"))

# Windows "Details" tab of Mucify.exe: product name, version, copyright (read from mucify/__init__.py)
import re, tempfile
_init = open(os.path.join(ROOT, "mucify", "__init__.py"), encoding="utf-8").read()
def _meta(name, default=""):
    m = re.search(name + r'\s*=\s*"([^"]*)"', _init)
    return m.group(1) if m else default
_ver = _meta("__version__", "0.0.0")
_nums = (tuple(int(x) for x in re.findall(r"\d+", _ver)) + (0, 0, 0, 0))[:4]
_vfile = os.path.join(tempfile.mkdtemp(prefix="mucify-ver-"), "version_info.txt")
with open(_vfile, "w", encoding="utf-8") as _f:
    _f.write("""VSVersionInfo(
  ffi=FixedFileInfo(filevers=%s, prodvers=%s, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', %r),
      StringStruct('FileDescription', 'Mucify'),
      StringStruct('FileVersion', %r),
      StringStruct('InternalName', 'Mucify'),
      StringStruct('LegalCopyright', %r),
      StringStruct('OriginalFilename', 'Mucify.exe'),
      StringStruct('ProductName', 'Mucify'),
      StringStruct('ProductVersion', %r)])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ])
""" % (_nums, _nums, _meta("__author__", "Mucify"), _ver, _meta("__copyright__"), _ver))

hiddenimports = (
    collect_submodules("webview")
    + ["mutagen.flac", "mutagen.id3", "mutagen.mp4", "mutagen.oggvorbis", "mutagen.oggopus"]
    + collect_submodules("mucify")
)
if os.name == "nt":
    hiddenimports += ["clr", "clr_loader"]

a = Analysis(
    ["run_mucify.py"],
    pathex=[ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "PIL", "pytest", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Mucify",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                       # normal desktop app: no Command Prompt window
    icon=os.path.join(ROOT, "assets", "mucify.ico"),
    version=_vfile,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Mucify")
