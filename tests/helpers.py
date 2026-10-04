# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 mageman007 and contributors
"""Shared test setup: every test run gets its own private Mucify data + Music folders."""
import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="mucify-tests-"))
os.environ["MUCIFY_HOME"] = str(_TMP / "appdata")

from mucify import paths  # noqa: E402  (must come after MUCIFY_HOME is set)

paths.windows_music_dir = lambda: _TMP / "Music"          # never touch the real Music folder

from mucify import app as backend  # noqa: E402

HDR = {"X-Mucify": "1"}
