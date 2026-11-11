"""Restricted lifecycle CLI shipped by the daemon-only distribution."""

import argparse
import logging
import sys

from ai_guardian import __version__

logger = logging.getLogger(__name__)


def _parser():
    parser = argparse.ArgumentParser(
        prog="ai-guardian-daemon",
        description="Manage the headless AI Guardian daemon and REST API.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"ai-guardian-daemon {__version__}",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    init_config = commands.add_parser(
        "init-config", help="Create the default global configuration if absent"
    )
    init_config.set_defaults(command="init-config")

    start = commands.add_parser("start", help="Start the daemon")
    start.add_argument(
        "-b", "--background", action="store_true", help="Run in the background"
    )
    start.add_argument(
        "--idle-timeout",
        type=float,
        default=0,
        metavar="MINUTES",
        help="Stop after this many idle minutes (0 disables the timeout)",
    )

    commands.add_parser("status", help="Show daemon and REST API readiness")
    commands.add_parser("stop", help="Stop the daemon")
    commands.add_parser("restart", help="Restart the daemon in the background")
    return parser


def _clear_stop_request():
    """Allow an explicit start to clear the previous stop marker."""
    from ai_guardian.daemon import get_state_dir

    marker = get_state_dir() / "daemon.stop-requested"
    try:
        marker.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Unable to clear daemon stop marker: %s", exc)


def _start_background(idle_timeout):
    from ai_guardian.daemon.client import start_daemon_background

    command = [sys.executable, "-m", "ai_guardian.daemon_cli", "start"]
    if idle_timeout:
        command.extend(["--idle-timeout", str(idle_timeout)])
    if start_daemon_background(daemon_command=command):
        print("AI Guardian daemon started in the background")
        return 0
    print("Failed to start AI Guardian daemon", file=sys.stderr)
    return 1


def _start_foreground(idle_timeout):
    from ai_guardian.daemon.server import DaemonServer

    server = DaemonServer(idle_timeout=idle_timeout * 60)
    try:
        server.start()
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


def _init_config():
    from ai_guardian.config.utils import get_config_dir
    from ai_guardian.setup.config import create_default_config

    config_path = get_config_dir() / "ai-guardian.json"
    existed = config_path.exists()
    success, detail = create_default_config()
    if not success:
        print(detail, file=sys.stderr)
        return 1
    if existed:
        print(f"Existing configuration preserved: {config_path}")
    else:
        print(f"Created default configuration: {config_path}")
        print("Set daemon.rest_tls and restart the daemon to enable HTTPS.")
    return 0


def main(argv=None):
    """Run the daemon-only lifecycle commands."""
    args = _parser().parse_args(argv)

    if args.command == "init-config":
        return _init_config()
    if args.command == "start":
        _clear_stop_request()
        if args.background:
            return _start_background(args.idle_timeout)
        return _start_foreground(args.idle_timeout)

    from ai_guardian.cli_handlers import _handle_daemon_command

    if args.command == "restart":
        if _handle_daemon_command(argparse.Namespace(daemon_command="stop")) != 0:
            return 1
        _clear_stop_request()
        return _start_background(0)

    return _handle_daemon_command(argparse.Namespace(daemon_command=args.command))


if __name__ == "__main__":
    raise SystemExit(main())
