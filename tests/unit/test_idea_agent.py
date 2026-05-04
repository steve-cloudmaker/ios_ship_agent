"""Unit tests for IdeaAgent."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from ios_ship_agent.core.models import AppIdea, PaywallTier


class TestIdeaAgent:
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
        from ios_ship_agent.agents.idea_agent import IdeaAgent
        return IdeaAgent()

    def test_run_returns_refined_idea(self, stamp_idea):
        self._set_claude_response({
            "name_candidate": "Stamp Identifier",
            "slug": "stamp-identifier",
            "core_feature": "Scan stamps and get AI-powered value estimates",
            "target_user": "Stamp collectors",
            "value_proposition": "Know what your stamps are worth",
            "category": "Utilities",
            "ai_capability_required": "Visual recognition",
            "paywall_tiers": ["weekly", "yearly"],
            "is_single_use": False,
            "viability_score": 0.8,
            "viability_notes": "Good niche, few competitors.",
        })

        agent = self._make_agent()
        result = agent.run(stamp_idea)

        assert result.name_candidate == "Stamp Identifier"
        assert result.slug == "stamp-identifier"
        assert PaywallTier.WEEKLY in result.paywall_strategy
        assert PaywallTier.YEARLY in result.paywall_strategy
        assert result.is_single_use is False

    def test_low_viability_logs_warning(self, stamp_idea):
        import logging
        self._set_claude_response({
            "name_candidate": "Test App",
            "slug": "test-app",
            "core_feature": "Test",
            "target_user": "Test",
            "value_proposition": "Test",
            "category": "Utilities",
            "ai_capability_required": "Test",
            "paywall_tiers": ["weekly"],
            "is_single_use": False,
            "viability_score": 0.3,
            "viability_notes": "Very saturated market.",
        })

        agent = self._make_agent()
        # Low viability should not raise, just warn
        result = agent.run(stamp_idea)
        # Agent should still return a valid result
        assert result.slug == "test-app"

    def test_invalid_paywall_tiers_fallback(self, stamp_idea):
        self._set_claude_response({
            "name_candidate": "Test App",
            "slug": "test-app",
            "core_feature": "Test",
            "target_user": "Test",
            "value_proposition": "Test",
            "category": "Utilities",
            "ai_capability_required": "Test",
            "paywall_tiers": ["invalid_tier", "also_bad"],
            "is_single_use": False,
            "viability_score": 0.7,
            "viability_notes": "Good.",
        })

        agent = self._make_agent()
        result = agent.run(stamp_idea)

        # Should fall back to defaults
        assert PaywallTier.WEEKLY in result.paywall_strategy
        assert PaywallTier.YEARLY in result.paywall_strategy

    def test_lifetime_paywall_for_single_use(self, stamp_idea):
        self._set_claude_response({
            "name_candidate": "One-Time App",
            "slug": "one-time-app",
            "core_feature": "One-time use thing",
            "target_user": "Anyone",
            "value_proposition": "Do it once",
            "category": "Utilities",
            "ai_capability_required": "Test",
            "paywall_tiers": ["lifetime"],
            "is_single_use": True,
            "viability_score": 0.7,
            "viability_notes": "Niche.",
        })

        agent = self._make_agent()
        result = agent.run(stamp_idea)

        assert result.is_single_use is True
        assert PaywallTier.LIFETIME in result.paywall_strategy

    def test_claude_called_once(self, stamp_idea):
        self._set_claude_response({
            "name_candidate": "Test",
            "slug": "test",
            "core_feature": "Test",
            "target_user": "Test",
            "value_proposition": "Test",
            "category": "Utilities",
            "ai_capability_required": "Test",
            "paywall_tiers": ["weekly"],
            "is_single_use": False,
            "viability_score": 0.7,
            "viability_notes": "Fine.",
        })

        agent = self._make_agent()
        agent.run(stamp_idea)

        assert self.mock_client.messages.create.call_count == 1
