# Changelog

All notable changes to Mucify are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-10-04

First public release.

### The workflow
- **Playlist Manager:** keeps a library of songs you already have (by Spotify track ID), compares new playlists against it, and backs the library up to one CSV.
- **Qobuz Enrich:** cleans track names and adds each song's official maximum bit depth and sample rate (optional; defaults to 24-bit / 48 kHz without Qobuz). If the Qobuz connection expires, the run stops and asks you to reconnect.
- **Downloader:** finds the best matching FLAC on Soulseek with the bundled, tested `sldl` 2.6.0. FLAC only, never lower quality than the first pick, up to 15 attempts per song, stalled sources are dropped.
- **Post-Processing:** ReplayGain 2.0 tags for your FLAC library with the bundled `rsgain`.
- **One folder per playlist** with `1_to_download.csv`, `2_enriched.csv`, `3_skipped.csv` and `4_successful.csv`, saved automatically.

### The app
- Native Windows desktop app and installer (no Python, Docker, WSL or browser needed). About 26 MB.
- First-run setup: Soulseek login with random credentials and *Test connection*, optional Qobuz connection (in-app sign-in, manual token fallback), automatic folders.
- **Guide** page explaining the workflow, why the Playlist Manager exists and where every file is saved.
- **Mini player** in the sidebar and background music from one file or a whole shuffled folder (MP3/FLAC), with cover art.
- Remembers whether the window was maximized, plus its size and position. **F11** toggles fullscreen.
- *Reset* and *Uninstall* tools that clear everything Mucify stored.
- Open source under GPL-3.0-or-later with licence, credits, privacy and disclaimer documents (also shown in the app).
