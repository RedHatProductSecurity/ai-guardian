"""Initializer template for the daemon-only wheel; version is build-generated."""

from ai_guardian._daemon_bootstrap import configure_daemon_logging

__version__ = "__DAEMON_VERSION__"
logger = configure_daemon_logging(__version__)
