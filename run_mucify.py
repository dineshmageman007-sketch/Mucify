# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 mageman007 and contributors
"""PyInstaller entry point (the package uses relative imports, so it can't be the entry itself)."""
import multiprocessing

from mucify.main import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
