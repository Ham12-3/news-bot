import logging
import sys
from datetime import datetime
import json
from typing import Any


class StructuredFormatter(logging.Formatter):
    """JSON structured logging formatter."""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add extra fields if present
        if hasattr(record, "extra_data"):
            log_data["data"] = record.extra_data

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data)


class StructuredLogger(logging.Logger):
    """Logger that supports structured data."""

    def _log_with_data(
        self,
        level: int,
        msg: str,
        data: dict[str, Any] | None = None,
        *args,
        **kwargs
    ):
        if data:
            extra = kwargs.get("extra", {})
            extra["extra_data"] = data
            kwargs["extra"] = extra
        super()._log(level, msg, args, **kwargs)

    def info_with_data(self, msg: str, data: dict[str, Any] | None = None, **kwargs):
        self._log_with_data(logging.INFO, msg, data, **kwargs)

    def error_with_data(self, msg: str, data: dict[str, Any] | None = None, **kwargs):
        self._log_with_data(logging.ERROR, msg, data, **kwargs)

    def warning_with_data(self, msg: str, data: dict[str, Any] | None = None, **kwargs):
        self._log_with_data(logging.WARNING, msg, data, **kwargs)


def setup_logging(debug: bool = False) -> None:
    """Configure structured logging for the application."""
    logging.setLoggerClass(StructuredLogger)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG if debug else logging.INFO)

    # Clear existing handlers
    root_logger.handlers.clear()

    # Console handler with structured output
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(StructuredFormatter())
    root_logger.addHandler(console_handler)

    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


def get_logger(name: str) -> StructuredLogger:
    """Get a structured logger instance."""
    return logging.getLogger(name)  # type: ignore
