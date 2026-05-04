"""Unit tests for KeywordAgent."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
import requests


class TestKeywordAgent:
    @pytest.fixture(autouse=True)
    def patch_deps(self):
        with patch("anthropic.Anthropic") as mock_anthropic_cls, \
             patch("requests.Session") as mock_session_cls:
            self.mock_anthropic = MagicMock()
            mock_anthropic_cls.return_value = self.mock_anthropic
            self.mock_session = MagicMock()
            mock_session_cls.return_value = self.mock_session
            yield

    def _set_suggest_response(self, terms: list[str]) -> None:
        resp = MagicMock()
        resp.json.return_value = {"hints": [{"term": t} for t in terms]}
        resp.raise_for_status.return_value = None
        self.mock_session.get.return_value = resp

    def _set_claude_score_response(self, keywords: list[str]) -> None:
        scored = [
            {
                "term": kw,
                "popularity_score": 50,
                "competition_score": 30,
                "app_count": 5,
                "opportunity_score": 0.0,
                "source": "test",
            }
            for kw in keywords
        ]
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps(scored))]
        self.mock_anthropic.messages.create.return_value = mock_response

    def _make_agent(self):
        from ios_ship_agent.agents.keyword_agent import KeywordAgent
        return KeywordAgent()

    def test_run_returns_result(self, refined_stamp):
        terms = ["stamp identifier", "stamp value", "postage scanner"]
        self._set_suggest_response(terms)
        self._set_claude_score_response(terms)

        agent = self._make_agent()
        result = agent.run(refined_stamp)

        assert result.primary_keyword is not None
        assert result.keyword_string is not None
        assert len(result.keyword_string) <= 100

    def test_keyword_string_never_exceeds_100_chars(self, refined_stamp):
        terms = ["stamp identifier", "stamp value", "postage scanner", "philately app"]
        self._set_suggest_response(terms)

        # Claude returns a very long keyword string (agent must trim)
        long_string = ",".join(["philately"] * 30)  # way over 100
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps([
            {
                "term": t,
                "popularity_score": 50,
                "competition_score": 30,
                "app_count": 5,
                "opportunity_score": 0.0,
                "source": "test",
            }
            for t in terms
        ]))]
        self.mock_anthropic.messages.create.return_value = mock_response

        # Override the string builder response separately
        call_count = [0]
        def side_effect(**kwargs):
            call_count[0] += 1
            resp = MagicMock()
            if call_count[0] == 1:
                resp.content = [MagicMock(text=json.dumps([
                    {"term": t, "popularity_score": 50, "competition_score": 30,
                     "app_count": 5, "opportunity_score": 0.0, "source": "test"}
                    for t in terms
                ]))]
            else:
                resp.content = [MagicMock(text=long_string)]
            return resp

        self.mock_anthropic.messages.create.side_effect = side_effect

        agent = self._make_agent()
        result = agent.run(refined_stamp)

        assert len(result.keyword_string) <= 100

    def test_dry_run_returns_fixture(self, refined_stamp):
        import os
        os.environ["DRY_RUN"] = "true"
        try:
            # Must reload settings after env change
            import importlib
            import ios_ship_agent.core.config as cfg_module
            importlib.reload(cfg_module)
            from ios_ship_agent.core.config import settings
            object.__setattr__(settings, "DRY_RUN", True)

            from ios_ship_agent.agents.keyword_agent import KeywordAgent
            agent = KeywordAgent()
            result = agent._dry_run_result(refined_stamp)
            assert result.primary_keyword.source == "dry_run"
        finally:
            os.environ["DRY_RUN"] = "false"

    def test_fallback_scores_when_claude_fails(self, refined_stamp):
        from ios_ship_agent.agents.keyword_agent import KeywordAgent
        agent = KeywordAgent()

        keywords = ["stamp identifier", "stamp value", "postage"]
        scores = agent._fallback_scores(keywords)

        assert len(scores) == 3
        for score in scores:
            assert score.opportunity_score >= 0

    def test_primary_keyword_has_highest_opportunity(self, refined_stamp):
        self._set_suggest_response(["a", "b", "c"])
        scored_data = [
            {"term": "a", "popularity_score": 30, "competition_score": 80, "app_count": 50, "opportunity_score": 0.0, "source": "test"},
            {"term": "b", "popularity_score": 70, "competition_score": 30, "app_count": 5, "opportunity_score": 0.0, "source": "test"},
            {"term": "c", "popularity_score": 50, "competition_score": 50, "app_count": 20, "opportunity_score": 0.0, "source": "test"},
        ]
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps(scored_data))]
        self.mock_anthropic.messages.create.return_value = mock_response

        agent = self._make_agent()
        result = agent.run(refined_stamp)

        # "b" has highest opportunity: (70*0.6 - 30*0.4)/100 = (42-12)/100 = 0.3
        assert result.primary_keyword.term == "b"
