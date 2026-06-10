"""PyInstaller runtime hook: point tiktoken at the bundled BPE cache.

Without this, the first call to ``tiktoken.get_encoding('cl100k_base')``
inside the packaged .exe would try to download the merge file from
``openaipublic.blob.core.windows.net`` — which fails on offline machines
and triggers AV / corporate proxy warnings on online ones.

The cache directory is laid down by aianalyzer.spec via ``datas`` and
ends up at ``_MEIPASS/tiktoken_cache/`` when the bootloader extracts.
"""
from __future__ import annotations

import os
import sys


def _set_tiktoken_cache_dir() -> None:
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        return
    cache_dir = os.path.join(base, "tiktoken_cache")
    if os.path.isdir(cache_dir):
        os.environ.setdefault("TIKTOKEN_CACHE_DIR", cache_dir)


_set_tiktoken_cache_dir()
