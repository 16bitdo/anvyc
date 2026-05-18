"""Rich 기반 logger helper."""
from __future__ import annotations

import logging

from rich.logging import RichHandler

_LOGGER_NAME = "anvyc"


def get_logger() -> logging.Logger:
    logger = logging.getLogger(_LOGGER_NAME)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        handler = RichHandler(rich_tracebacks=True, markup=True, show_time=False)
        logger.addHandler(handler)
        logger.propagate = False
    return logger
