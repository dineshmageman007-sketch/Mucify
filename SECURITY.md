# Security policy

## Reporting a vulnerability
Please **do not** post security problems in a public issue. Use GitHub's private reporting instead:
open the repository's **Security** tab and choose **Report a vulnerability**. Include what you found,
how to reproduce it and the Mucify version (shown in *Settings*). You'll get a reply as soon as
practical, and a fix will be released before details are made public.

Only the latest release is supported with fixes.

## Things that are by design
- Mucify stores your Soulseek password and Qobuz token in plain text in `%APPDATA%\Mucify` (see
  [PRIVACY.md](PRIVACY.md)). Protect your Windows user account accordingly.
- The bundled `sldl.exe` and `rsgain.exe` are unmodified upstream programs. Report problems in those
  programs to their own projects.
