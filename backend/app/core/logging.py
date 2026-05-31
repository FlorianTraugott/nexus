"""Structured logging configuration.

Why structured logging? Instead of free-text log lines, every log entry is a
structured record with named fields (timestamp, level, event, plus any context
you attach). In production these are emitted as JSON, which log aggregators
(Datadog, CloudWatch, Grafana Loki, etc.) can index and query. In development
they're rendered as readable, colourised lines for humans.

Usage:
    from app.core.logging import configure_logging, get_logger

    configure_logging()                 # call once at startup
    log = get_logger(__name__)
    log.info("user_registered", user_id=123, email="a@b.com")
"""

import logging

import structlog

from app.core.config import get_settings


def configure_logging() -> None:
    """Configure structlog for the whole application.

    Development (DEBUG=true): human-readable, colourised console output.
    Production  (DEBUG=false): one JSON object per line.
    Call this once, as early as possible during startup.
    """
    settings = get_settings()

    # Processors run in order, transforming each log event before rendering.
    shared_processors: list[structlog.types.Processor] = [
        # Merge any context bound via structlog.contextvars (e.g. request IDs,
        # which we add in Part 10).
        structlog.contextvars.merge_contextvars,
        # Add the log level as a field ("info", "error", ...).
        structlog.processors.add_log_level,
        # Render exception info when present.
        structlog.processors.StackInfoRenderer(),
        # ISO-8601 timestamp.
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    # Choose the final renderer based on environment.
    renderer: structlog.types.Processor
    if settings.DEBUG:
        renderer = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[*shared_processors, renderer],
        # Filter out logs below the configured level for performance.
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.DEBUG if settings.DEBUG else logging.INFO
        ),
        context_class=dict,
        # Write to stdout — the right destination for containerised apps.
        logger_factory=structlog.PrintLoggerFactory(),
        # Cache the logger after first use for performance.
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger, optionally named (usually `__name__`)."""
    # structlog.get_logger is typed as returning Any; we expose the concrete
    # BoundLogger type to callers for better editor autocomplete.
    return structlog.get_logger(name)  # type: ignore[no-any-return]
