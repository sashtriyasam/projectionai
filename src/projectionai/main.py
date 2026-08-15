"""Command-line entry point for ProjectionAI.

Usage::

    python -m projectionai                # Launch the GUI application
    python -m projectionai --help         # Show usage
"""

from __future__ import annotations

import argparse
import sys


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="projectionai",
        description="AI-powered projection mapping platform",
    )
    _ = parser.add_argument(
        "--version",
        action="store_true",
        help="Print version and exit",
    )
    _ = parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to a YAML configuration file",
    )
    _ = parser.add_argument(
        "--log-level",
        type=str,
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Override the log level",
    )
    _ = parser.add_argument(
        "--no-splash",
        action="store_true",
        help="Skip the startup splash screen",
    )
    _ = parser.add_argument(
        "project",
        nargs="?",
        type=str,
        default=None,
        help="Path to a .projectionai project file to open",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Application entry point."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.version:
        from projectionai import __version__

        print(f"ProjectionAI v{__version__}")
        return 0

    # Install exception hooks early so config/init failures surface
    # as the error dialog instead of a raw traceback.
    from projectionai.ui.dialogs.error_dialog import install_exception_hooks

    install_exception_hooks()

    # Configure logging
    from projectionai.core.config import load_config
    from projectionai.core.logging import configure_logging

    config = load_config(args.config)
    if args.log_level:
        config.log_level = args.log_level

    configure_logging(config)

    # Launch the Qt application
    from projectionai.app import run_app

    return run_app(
        config,
        project_path=args.project,
        show_splash=not args.no_splash,
    )


if __name__ == "__main__":
    sys.exit(main())
