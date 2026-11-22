"""PipeTerminal desktop application entry point."""

import sys

from app.crash_log import install_crash_logging


def main() -> int:
    install_crash_logging(__file__)
    from app.bootstrap import run

    return run()


if __name__ == "__main__":
    sys.exit(main())
