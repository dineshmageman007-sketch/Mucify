# Privacy

Mucify runs on your PC. It has **no accounts, no ads, no analytics and no telemetry**, and the author
does not receive any of your data.

## What Mucify stores on your PC
Everything lives in `%APPDATA%\Mucify` (usually `C:\Users\<you>\AppData\Roaming\Mucify`), plus the music
and working folders you choose (by default `Music\Mucify`).

| What | Where | Notes |
|---|---|---|
| Soulseek username and password | `config.json`, and `tools\sldl\sldl.conf` | **Stored as plain text** so the downloader can log in. Anyone who can read your user folder can read them. |
| Qobuz token (if you connect Qobuz) | `config.json` | **Plain text.** It gives access to your Qobuz account like a login, so never share it. |
| Qobuz login-window data | `webview\` | Browser cookies and local storage from the Qobuz sign-in window, kept so you stay signed in. |
| Your library index and imported playlists | `data\` | Track names, artists and Spotify track IDs from CSV files you imported. |
| Playlist work files | the Working folder | The `1_`…`4_` CSV lists for each playlist. |
| Logs | `logs\` | Local diagnostic and crash logs. Nothing is sent anywhere. |

## Network connections Mucify makes
- **Soulseek** (`server.slsknet.org`): when you press *Test connection* and whenever the downloader runs.
  Other Soulseek users can see your Soulseek username while you are connected or downloading from them.
- **Qobuz** (`www.qobuz.com` API and `play.qobuz.com` in the sign-in window): to look up track quality using your token and to
  let you sign in. Qobuz's own privacy policy applies to that traffic.
- **Links you click** (for example chosic.com or qobuz.com) open in your normal web browser.
- **Microsoft Edge WebView2** draws Mucify's window. It is a Microsoft component and the installer may
  download it from Microsoft if your PC does not have it yet. Microsoft's terms apply to it.
- Mucify does not check for updates and does not contact any server run by its author.

## The local service
To show its window, Mucify starts a small web service that only listens on your own PC (`127.0.0.1`, random
port). It rejects requests that do not come from Mucify's own window.

## Removing your data
*Settings → Reset & uninstall* clears everything above (your music is only deleted if you tick that box),
and the Windows uninstaller offers the same clean-up.
