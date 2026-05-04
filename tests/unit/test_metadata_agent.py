"""Unit tests for MetadataAgent."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


class TestMetadataAgent:
    @pytest.fixture(autouse=True)
    def patch_anthropic(self):
        with patch("anthropic.Anthropic") as mock_cls:
            self.mock_client = MagicMock()
            mock_cls.return_value = self.mock_client
            yield

    def _set_claude_response(self, data: dict) -> None:
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps(data))]
        self.mock_client.messages.create.return_value = mock_response

    def _make_agent(self):
        from ios_ship_agent.agents.metadata_agent import MetadataAgent
        return MetadataAgent()

    def _valid_metadata_response(self) -> dict:
        return {
            "app_name": "Stamp Identifier",
            "subtitle": "AI Scanner & Value",
            "description": "Discover the value in your stamps. Point your camera at any stamp and get AI-powered identification, value estimates, and historical context.",
            "keywords": "stamp,philately,postage,collector,coins,antique,value",
            "promotional_text": "New: Real-time auction prices!",
            "primary_category": "Utilities",
            "secondary_category": None,
            "age_rating": "4+",
            "onboarding_titles": [
                "Scan Any Stamp",
                "Discover Its Value",
                "Build Your Collection",
            ],
            "paywall_titles": [
                "Unlimited Scans",
                "Full History",
                "AI Analysis",
                "Ad-Free",
            ],
            "screenshot_headlines": [
                "Point. Scan. Identify.",
                "Know Its Worth",
                "Your Collection",
                "History View",
                "Trusted By Collectors",
            ],
        }

    def test_run_returns_valid_metadata(self, refined_stamp, keyword_result, aso_result):
        self._set_claude_response(self._valid_metadata_response())

        agent = self._make_agent()
        result = agent.run(refined_stamp, keyword_result, aso_result)

        assert len(result.app_name) <= 30
        assert len(result.subtitle) <= 30
        assert len(result.keywords) <= 100
        assert len(result.description) <= 4000

    def test_app_name_over_30_is_trimmed(self, refined_stamp, keyword_result, aso_result):
        data = self._valid_metadata_response()
        data["app_name"] = "A" * 35  # over limit
        self._set_claude_response(data)

        agent = self._make_agent()
        result = agent.run(refined_stamp, keyword_result, aso_result)

        assert len(result.app_name) <= 30

    def test_keywords_over_100_are_trimmed(self, refined_stamp, keyword_result, aso_result):
        data = self._valid_metadata_response()
        data["keywords"] = ",".join(["keyword"] * 20)  # way over 100
        self._set_claude_response(data)

        agent = self._make_agent()
        result = agent.run(refined_stamp, keyword_result, aso_result)

        assert len(result.keywords) <= 100

    def test_keywords_no_spaces_after_commas(self, refined_stamp, keyword_result, aso_result):
        data = self._valid_metadata_response()
        data["keywords"] = "stamp, philately, postage, collector"
        self._set_claude_response(data)

        agent = self._make_agent()
        result = agent.run(refined_stamp, keyword_result, aso_result)

        assert ", " not in result.keywords

    def test_onboarding_titles_populated(self, refined_stamp, keyword_result, aso_result):
        self._set_claude_response(self._valid_metadata_response())

        agent = self._make_agent()
        result = agent.run(refined_stamp, keyword_result, aso_result)

        assert len(result.onboarding_titles) >= 3

    def test_paywall_titles_populated(self, refined_stamp, keyword_result, aso_result):
        self._set_claude_response(self._valid_metadata_response())

        agent = self._make_agent()
        result = agent.run(refined_stamp, keyword_result, aso_result)

        assert len(result.paywall_titles) == 4

    def test_screenshot_headlines_populated(self, refined_stamp, keyword_result, aso_result):
        self._set_claude_response(self._valid_metadata_response())

        agent = self._make_agent()
        result = agent.run(refined_stamp, keyword_result, aso_result)

        assert len(result.screenshot_headlines) == 5

    def test_enforce_limit_trims_at_word_boundary(self):
        agent = self._make_agent()
        long_text = "word " * 10  # 50 chars
        result = agent._enforce_limit(long_text.strip(), max_chars=20)
        assert len(result) <= 20
        # Should end at a word boundary
        assert not result.endswith(" ")

    def test_enforce_keywords_removes_spaces(self):
        agent = self._make_agent()
        result = agent._enforce_keywords("stamp, philately, postage")
        assert ", " not in result

    def test_enforce_keywords_trims_to_100(self):
        agent = self._make_agent()
        long = ",".join(["longkeyword"] * 15)
        result = agent._enforce_keywords(long)
        assert len(result) <= 100
