"""
Rotating-file + console logger factory.

Usage:
    from src.common.logging_setup import setup_logger
    logger = setup_logger("central_monitor", "C:/P3DMonitor/logs/central_monitor.log")
"""

import logging
import logging.handlers
from pathlib import Path


def setup_logger(name: str, log_path: str | Path, level: int = logging.INFO) -> logging.Logger:
    """
    Return a named logger that writes to both a rotating file and the console.

    Rotating policy: 5 MB per file, keep 5 backups.
    Re-using the same name is safe — handlers are only added once.
    
    Args:
        name: Logger name (e.g., "central_monitor")
        log_path: Path to log file (str or Path)
        level: Log level (default: logging.INFO)
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)

    # Avoid adding duplicate handlers if setup_logger is called more than once
    if logger.handlers:
        return logger

    log_path_obj = Path(log_path) if isinstance(log_path, str) else log_path
    log_path_obj.parent.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Rotating file handler
    fh = logging.handlers.RotatingFileHandler(
        str(log_path_obj),
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=5,
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # Console handler
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    return logger
