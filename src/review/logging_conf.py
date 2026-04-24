"""
Centralized logging configuration.

- Safe in async and concurrent contexts.
- Optional JSON logging if 'python-json-logger' is installed (graceful fallback).
- Optional rotating file handler.
- Convenience helpers: get_logger(), log_timing()

Usage:
    from wildcv_review.logging_conf import setup_logging, get_logger, log_timing
    setup_logging(level="INFO", json_logs=False, log_file="run.log")

    log = get_logger(__name__)
    with log_timing(log, "processed batch"):
        ...
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import time
from contextlib import contextmanager
from typing import Iterator, Optional


def _build_formatter(json_logs: bool) -> logging.Formatter:
    """
    If python-json-logger is available and json_logs=True, use it.
    Otherwise fall back to a human-friendly line formatter.
    """
    if json_logs:
        try:
            from pythonjsonlogger import jsonlogger  # type: ignore
        except Exception:
            # Fallback to plain text if dependency not present
            pass
        else:
            return jsonlogger.JsonFormatter(
                "%(asctime)s %(levelname)s %(name)s %(message)s",
                rename_fields={"levelname": "level", "asctime": "time"},
            )

    return logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def setup_logging(
    *,
    level: str = "INFO",
    json_logs: bool = False,
    log_file: Optional[str] = None,
    rotate_megabytes: int = 10,
    rotate_backups: int = 5,
) -> None:
    """
    Initialize root logging once for the whole application.

    Args:
        level: Logging level name (e.g., 'INFO', 'DEBUG').
        json_logs: Emit logs as JSON if possible.
        log_file: Optional path to a rotating log file.
        rotate_megabytes: Max size per file for rotation.
        rotate_backups: Number of rotated backups to keep.
    """
    # Avoid reconfiguring if already configured
    root = logging.getLogger()
    if getattr(root, "_wildcv_logging_configured", False):
        return

    # Clear any preexisting handlers (e.g., when running in notebooks)
    for h in list(root.handlers):
        root.removeHandler(h)

    lvl = getattr(logging, level.upper(), logging.INFO)
    root.setLevel(lvl)

    formatter = _build_formatter(json_logs)

    # Console handler
    ch = logging.StreamHandler()
    ch.setFormatter(formatter)
    ch.setLevel(lvl)
    root.addHandler(ch)

    # Optional rotating file handler
    if log_file:
        os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            filename=log_file,
            maxBytes=rotate_megabytes * 1024 * 1024,
            backupCount=rotate_backups,
            encoding="utf-8",
        )
        fh.setFormatter(formatter)
        fh.setLevel(lvl)
        root.addHandler(fh)

    # Mark configured
    setattr(root, "_wildcv_logging_configured", True)


def get_logger(name: str) -> logging.Logger:
    """
    Convenience shortcut that encourages module-level loggers.
    """
    return logging.getLogger(name)


@contextmanager
def log_timing(logger: logging.Logger, message: str) -> Iterator[None]:
    """
    Context manager that logs elapsed time on exit at INFO level.
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = (time.perf_counter() - start) * 1000.0
        logger.info("%s in %.1f ms", message, elapsed)
