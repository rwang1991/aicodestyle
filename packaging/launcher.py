"""PyInstaller entry point for the standalone Windows .exe.

When the user double-clicks ``aianalyzer.exe`` (no CLI args), we transparently
invoke the ``serve`` sub-command so the portal launches and the browser opens.
Power users can still pass any CLI verb (``aianalyzer.exe scan``,
``aianalyzer.exe report``, ``aianalyzer.exe serve --port 9000``) and it
behaves exactly like the installed package.

This file lives outside ``src/aianalyzer`` so it never ships with the wheel —
it exists purely for the frozen-executable build.
"""
from __future__ import annotations

import sys


def main() -> None:
    # Default to the portal when the user double-clicks the .exe with no args.
    # Detect by counting argv entries: PyInstaller always sets argv[0] to the
    # exe path, so "no args" means len(argv) == 1.
    if len(sys.argv) == 1:
        sys.argv.append("serve")

    # Import here so PyInstaller's static analysis picks up the package as a
    # dependency, but we don't pay the import cost until we actually need it.
    from aianalyzer.cli import app

    app(prog_name="aianalyzer")


if __name__ == "__main__":
    main()
