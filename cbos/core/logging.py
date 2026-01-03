"""Centralized logging configuration for CBOS"""

import logging
import os
import sys
from typing import Optional


def setup_logging(
    level: Optional[str] = None,
    log_file: Optional[str] = None,
) -> logging.Logger:
    """
    Configure logging for CBOS.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR).
               Defaults to CBOS_LOG_LEVEL env var or INFO.
        log_file: Optional file path to write logs.
                  Defaults to CBOS_LOG_FILE env var.

    Returns:
        Root logger for cbos
    """
    level = level or os.environ.get("CBOS_LOG_LEVEL", "INFO")
    log_file = log_file or os.environ.get("CBOS_LOG_FILE")

    # Convert string level to logging constant
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    # Create formatter
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Configure root cbos logger
    root_logger = logging.getLogger("cbos")
    root_logger.setLevel(numeric_level)

    # Clear existing handlers
    root_logger.handlers.clear()

    # Console handler (stderr)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler (optional)
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger for a CBOS component.

    Args:
        name: Component name (e.g., "screen", "store", "api")

    Returns:
        Logger instance
    """
    return logging.getLogger(f"cbos.{name}")
