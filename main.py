"""PipeTerminal desktop application entry point."""

import sys

from app.bootstrap import run


def main() -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())
