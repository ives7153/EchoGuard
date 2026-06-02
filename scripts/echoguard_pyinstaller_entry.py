"""PyInstaller entrypoint for EchoGuard.

Keeping this wrapper outside the package lets the bundled app import
``upper_computer.main`` in package mode, which avoids optional fallback-import
warnings that are only needed for ``cd upper_computer && python main.py``.
"""

from upper_computer.main import main


if __name__ == "__main__":
    raise SystemExit(main())
