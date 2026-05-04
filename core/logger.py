"""
Structured logging for ios_ship_agent.
Uses Python's logging + rich for beautiful terminal output.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler
from rich.theme import Theme

_THEME = Theme(
    {
        "info": "bold cyan",
        "warning": "bold yellow",
        "error": "bold red",
        "success": "bold green",
        "agent": "bold magenta",
        "dim": "dim white",
    }
)

console = Console(theme=_THEME)

_handlers: list[logging.Handler] = []


def get_logger(name: str, level: str = "INFO", log_file: Path | None = None) -> logging.Logger:
    """
    Return a configured logger for the given name.

    Args:
        name: Logger name (usually __name__)
        level: Log level string
        log_file: Optional path to write logs to file

    Returns:
        Configured Logger instance
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger  # already configured

    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Rich console handler
    rich_handler = RichHandler(
        console=console,
        show_time=True,
        show_path=False,
        rich_tracebacks=True,
        tracebacks_show_locals=False,
        markup=True,
    )
    rich_handler.setFormatter(logging.Formatter("%(message)s", datefmt="[%X]"))
    logger.addHandler(rich_handler)

    # Optional file handler
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(file_handler)

    logger.propagate = False
    return logger


def log_agent_start(logger: logging.Logger, agent_name: str, context: str = "") -> None:
    logger.info(f"[agent]▶ {agent_name}[/agent] starting{' — ' + context if context else ''}")


def log_agent_success(logger: logging.Logger, agent_name: str, context: str = "") -> None:
    logger.info(f"[success]✓ {agent_name}[/success] completed{' — ' + context if context else ''}")


def log_agent_failure(logger: logging.Logger, agent_name: str, error: str) -> None:
    logger.error(f"[error]✗ {agent_name}[/error] failed — {error}")


def log_pipeline_banner(logger: logging.Logger, app_idea: str) -> None:
    console.rule("[bold magenta]iOS Ship Agent[/bold magenta]")
    logger.info(f"[info]App idea:[/info] {app_idea}")
    console.rule()
