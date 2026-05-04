"""Unit tests for ASOResearchAgent."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


class TestASOResearchAgent:
    @pytest.fixture(autouse=True)
    def patch_deps(self):
        with patch("anthropic.Anthropic") as mock_anthropic_cls, \
             patch("requests.Session") as mock_session_cls:
            self.mock_anthropic = MagicMock()
            mock_anthropic_cls.return_value = self.mock_anthropic
            self.mock_session = MagicMock()
            mock_session_cls.return_value = self.mock_session
            yield

    def _set_search_response(self, results: list[dict]) -> None:
        resp = MagicMock()
        resp.json.return_value = {"results": results, "resultCount": len(results)}
        resp.raise_for_status.return_value = None
        self.mock_session.get.return_value = resp

    def _set_claude_response(self, data: dict) -> None:
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=json.dumps(data))]
        self.mock_anthropic.messages.create.return_value = mock_response

    def _make_agent(self):
        from ios_ship_agent.agents.aso_research_agent import ASOResearchAgent
        return ASOResearchAgent()

    def _make_itunes_result(self, **kwargs) -> dict:
        base = {
            "trackId": 123456789,
            "trackName": "Stamp Scanner Pro",
            "artistName": "Indie Dev",
            "averageUserRating": 4.3,
            "userRatingCount": 245,
            "price": 0.0,
            "description": "Scan stamps with AI and get instant value estimates.",
            "primaryGenreName": "Utilities",
            "releaseDate": "2024-01-15T00:00:00Z",
            "artworkUrl512": "https://example.com/icon.png",
            "screenshotUrls": [],
        }
        base.update(kwargs)
        return base

    def test_run_returns_result(self, refined_stamp, keyword_result):
        self._set_search_response([self._make_itunes_result()])
        self._set_claude_response({
            "common_value_props": ["Instant identification"],
            "screenshot_themes": ["Scan now", "Know the value", "Build collection", "History", "Trust"],
            "paywall_patterns": ["Unlimited Scans", "Full History", "AI Analysis", "Ad-Free"],
            "market_gaps": ["No real-time auction data"],
        })

        agent = self._make_agent()
        result = agent.run(refined_stamp, keyword_result)

        assert result.keyword == keyword_result.primary_keyword.term
        assert len(result.competitors) >= 1
        assert len(result.paywall_patterns) == 4
        assert len(result.screenshot_themes) == 5

    def test_no_results_falls_back_to_synthesis(self, refined_stamp, keyword_result):
        self._set_search_response([])
        self._set_claude_response({
            "common_value_props": ["AI-powered"],
            "screenshot_themes": ["Theme 1", "Theme 2", "Theme 3", "Theme 4", "Theme 5"],
            "paywall_patterns": ["Bullet 1", "Bullet 2", "Bullet 3", "Bullet 4"],
            "market_gaps": ["Gap 1"],
        })

        agent = self._make_agent()
        result = agent.run(refined_stamp, keyword_result)

        # Should still return a valid result via synthesis
        assert result is not None
        assert result.keyword == keyword_result.primary_keyword.term

    def test_competitor_paywall_style_free_with_iap(self, refined_stamp, keyword_result):
        itunes_result = self._make_itunes_result(
            price=0.0,
            description="In-App Purchases available. Subscribe for unlimited scans.",
        )
        self._set_search_response([itunes_result])
        self._set_claude_response({
            "common_value_props": [],
            "screenshot_themes": ["t1", "t2", "t3", "t4", "t5"],
            "paywall_patterns": ["b1", "b2", "b3", "b4"],
            "market_gaps": [],
        })

        agent = self._make_agent()
        result = agent.run(refined_stamp, keyword_result)

        if result.competitors:
            assert result.competitors[0].paywall_style_guess == "subscription"

    def test_top_competitor_is_highest_rated_count(self, refined_stamp, keyword_result):
        results = [
            self._make_itunes_result(trackId=1, trackName="App A", userRatingCount=100),
            self._make_itunes_result(trackId=2, trackName="App B", userRatingCount=5000),
            self._make_itunes_result(trackId=3, trackName="App C", userRatingCount=300),
        ]
        self._set_search_response(results)
        self._set_claude_response({
            "common_value_props": [],
            "screenshot_themes": ["t1", "t2", "t3", "t4", "t5"],
            "paywall_patterns": ["b1", "b2", "b3", "b4"],
            "market_gaps": [],
        })

        agent = self._make_agent()
        result = agent.run(refined_stamp, keyword_result)

        if result.top_competitor:
            assert result.top_competitor.rating_count == 5000
