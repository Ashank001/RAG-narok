"""
logger.py — Shared structured JSON logger for the RAGnarok rag-engine service.

Usage:
    from logger import get_logger

    log = get_logger(__name__, session_id="abc-123")
    log.info("Cloning repository", extra={"repo_url": "https://github.com/..."})

Every emitted line is a JSON object that includes:
    timestamp  – ISO-8601 UTC
    level      – INFO / WARNING / ERROR / etc.
    service    – always "rag-engine"
    session_id – populated when provided, empty string otherwise
    message    – the log message
    + any extra fields passed via the `extra` kwarg
"""

import logging
import sys

# pyrefly: ignore [missing-import]
from pythonjsonlogger import jsonlogger  # type: ignore[import-untyped]


class _SessionFilter(logging.Filter):
    """
    Injects `service` and `session_id` into every LogRecord so the
    JsonFormatter can include them without callers needing to repeat them.
    """

    def __init__(self, session_id: str = "") -> None:
        super().__init__()
        self.session_id = session_id

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        record.service = "rag-engine"
        if not hasattr(record, "session_id"):
            record.session_id = self.session_id
        return True


def get_logger(name: str, session_id: str = "") -> logging.Logger:
    """
    Returns a logger named `name` that emits structured JSON to stdout.

    Args:
        name:       Typically __name__ of the calling module.
        session_id: Optional session identifier to bind to all records.

    Returns:
        A configured logging.Logger instance.
    """
    logger = logging.getLogger(name)

    # Avoid adding duplicate handlers when get_logger is called multiple times
    # (e.g. once at module level in main.py and once inside worker.py tasks).
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)

    # Fields included in every JSON log line (in this order):
    #   timestamp  level  service  session_id  message  + any extras
    # NOTE: use %(asctime)s in fmt — rename_fields renames it to "timestamp" in
    # the JSON output.  Using %(timestamp)s directly would produce null because
    # "timestamp" is not a native LogRecord attribute.
    fmt = "%(asctime)s %(levelname)s %(service)s %(session_id)s %(message)s"
    formatter = jsonlogger.JsonFormatter(
        fmt=fmt,
        rename_fields={"levelname": "level", "asctime": "timestamp"},
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )
    handler.setFormatter(formatter)
    handler.addFilter(_SessionFilter(session_id=session_id))

    logger.addHandler(handler)
    # Prevent log records from bubbling up to the root logger
    # (avoids duplicate output when uvicorn/celery configure their own root handler).
    logger.propagate = False

    return logger
