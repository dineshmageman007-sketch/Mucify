# Mucify architecture

```
Mucify.exe (PyInstaller, windowed)
 └─ mucify.main  ── starts Flask on 127.0.0.1:<random port> (thread) ── pywebview window (Edge WebView2)
      ├─ app.py        pipeline + setup endpoints  (data: %APPDATA%\Mucify)
      ├─ host.py       native dialogs / window handle shared with the backend
      ├─ qobuz_auth.py second window → play.qobuz.com, polls JS probe, validates token via API
      └─ tools/        sldl.exe (staged to %APPDATA%\Mucify\tools\sldl), rsgain.exe (run in place)
```
Installer: `installer/mucify.iss` (Inno Setup) wraps `dist\Mucify\`, adds shortcuts, installs WebView2 if missing.
