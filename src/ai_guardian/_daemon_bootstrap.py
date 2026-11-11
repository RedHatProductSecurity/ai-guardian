"""Small, standard-library-only package initialization for daemon builds."""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler


def configure_daemon_logging(version):
    """Configure private file and console logging without importing app features."""
    old_factory = logging.getLogRecordFactory()

    def record_factory(*args, **kwargs):
        record = old_factory(*args, **kwargs)
        record.version = version
        return record

    logging.setLogRecordFactory(record_factory)

    from ai_guardian.config.utils import get_state_dir, migrate_state_files
    from ai_guardian.storage import make_private_directory

    migrate_state_files()
    log_file = get_state_dir() / "ai-guardian.log"
    make_private_directory(log_file.parent)

    logger = logging.getLogger("ai_guardian")
    env_log_level = os.environ.get("AI_GUARDIAN_LOG_LEVEL", "").upper()
    if env_log_level and hasattr(logging, env_log_level):
        logger.setLevel(getattr(logging, env_log_level))
    elif logger.level == logging.NOTSET:
        logger.setLevel(logging.INFO)

    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s - v%(version)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(file_handler)

    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(stderr_handler)
    logger.propagate = False

    logger.debug("AI Guardian v%s initialized", version)
    logger.debug("Python %s", sys.version.split()[0])
    return logger
