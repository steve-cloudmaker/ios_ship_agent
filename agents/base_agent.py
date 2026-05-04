"""
Abstract base class for all pipeline agents.

Every agent:
  - Has a name
  - Has access to settings and a logger
  - Implements run() returning a typed result
  - Wraps run() in timing + status tracking
  - Can call Anthropic Claude for LLM tasks
"""

from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, TypeVar

import anthropic

from ios_ship_agent.core.config import settings
from ios_ship_agent.core.logger import get_logger
from ios_ship_agent.core.models import AgentRun, AgentStatus
from ios_ship_agent.core.retry import retry

T = TypeVar("T")


class BaseAgent(ABC):
    """Abstract base for all pipeline agents."""

    name: str = "BaseAgent"

    def __init__(self) -> None:
        self.logger = get_logger(
            f"ios_ship_agent.{self.name}",
            level=settings.LOG_LEVEL,
            log_file=settings.LOG_FILE if settings.LOG_FILE else None,
        )
        self._anthropic = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        self._run_record = AgentRun(agent_name=self.name)

    @abstractmethod
    def run(self, *args: Any, **kwargs: Any) -> Any:
        """Execute the agent's core logic."""
        ...

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        """
        Wrapper around run() that handles timing and status tracking.
        Call this from the orchestrator, not run() directly.
        """
        self._run_record.status = AgentStatus.RUNNING
        self._run_record.started_at = datetime.utcnow()
        start = time.monotonic()

        try:
            self.logger.info(f"[agent]{self.name}[/agent] starting")
            result = self.run(*args, **kwargs)
            self._run_record.status = AgentStatus.SUCCESS
            self.logger.info(f"[success]✓ {self.name}[/success] completed")
            return result
        except Exception as exc:
            self._run_record.status = AgentStatus.FAILED
            self._run_record.error = str(exc)
            self.logger.exception(f"[error]✗ {self.name}[/error] failed: {exc}")
            raise
        finally:
            elapsed = time.monotonic() - start
            self._run_record.duration_seconds = round(elapsed, 2)
            self._run_record.finished_at = datetime.utcnow()

    @property
    def run_record(self) -> AgentRun:
        return self._run_record

    # ------------------------------------------------------------------
    # Claude helpers
    # ------------------------------------------------------------------

    @retry(max_attempts=3, base_delay=2.0, exceptions=(anthropic.APIError, anthropic.RateLimitError))
    def _ask_claude(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int | None = None,
    ) -> str:
        """
        Send a prompt to Claude and return the text response.

        Args:
            prompt: User message
            system: Optional system prompt
            max_tokens: Override default max tokens

        Returns:
            Model response as string
        """
        messages: list[dict[str, str]] = [{"role": "user", "content": prompt}]

        kwargs: dict[str, Any] = {
            "model": settings.CLAUDE_MODEL,
            "max_tokens": max_tokens or settings.CLAUDE_MAX_TOKENS,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system

        response = self._anthropic.messages.create(**kwargs)
        text_blocks = [b.text for b in response.content if hasattr(b, "text")]
        return "\n".join(text_blocks).strip()

    @retry(max_attempts=3, base_delay=2.0, exceptions=(anthropic.APIError, anthropic.RateLimitError))
    def _ask_claude_json(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """
        Ask Claude for a JSON response and parse it.

        Returns:
            Parsed dict

        Raises:
            ValueError: If response is not valid JSON
        """
        json_system = (
            (system + "\n\n" if system else "")
            + "Respond ONLY with valid JSON. No markdown fences, no prose, no preamble."
        )
        raw = self._ask_claude(prompt, system=json_system, max_tokens=max_tokens)

        # Strip accidental markdown fences
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Claude returned invalid JSON: {exc}\nRaw:\n{raw}") from exc
