#!/usr/bin/env python3
"""Download argostranslate language models for Cerberus Proxy.

Run once after installation:

    python scripts/download_models.py

Each ``<lang> -> en`` model is fetched and installed locally. Models are
cached on disk, so re-running this script only installs what is missing.
"""
from __future__ import annotations

from lingua import Language

from cerberus_proxy.guards.translator import (
    SUPPORTED_LANGUAGES,
    ensure_language_models_installed,
)


def main() -> None:
    for language in SUPPORTED_LANGUAGES:
        if language == Language.ENGLISH:
            continue
        from_code = language.iso_code_639_1.name.lower()
        print(f"Installing {from_code} -> en model...")
        ensure_language_models_installed(from_code)
    print("All models installed.")


if __name__ == "__main__":
    main()
