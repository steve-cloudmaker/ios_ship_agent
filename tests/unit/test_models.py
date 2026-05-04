"""Unit tests for core/models.py"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ios_ship_agent.core.models import (
    AppIdea,
    AppStoreMetadata,
    KeywordOpportunity,
    KeywordResearchResult,
    PaywallTier,
    RefinedIdea,
)


class TestRefinedIdea:
    def test_valid_slug(self):
        idea = RefinedIdea(
            name_candidate="Plant Identifier",
            slug="plant-identifier",
            core_feature="Identify plants from photos",
            target_user="Gardeners",
            value_proposition="Know what plant you're looking at instantly",
            category="Utilities",
            ai_capability_required="plant recognition",
            paywall_strategy=[PaywallTier.WEEKLY],
        )
        assert idea.slug == "plant-identifier"

    def test_slug_with_uppercase_is_lowercased(self):
        idea = RefinedIdea(
            name_candidate="Test",
            slug="Plant-Identifier",
            core_feature="test",
            target_user="test",
            value_proposition="test",
            category="Utilities",
            ai_capability_required="test",
        )
        assert idea.slug == "plant-identifier"

    def test_slug_strips_invalid_chars(self):
        idea = RefinedIdea(
            name_candidate="Test",
            slug="my app!@#$%",
            core_feature="test",
            target_user="test",
            value_proposition="test",
            category="Utilities",
            ai_capability_required="test",
        )
        # spaces become hyphens, special chars are stripped
        assert idea.slug == "my-app"

    def test_empty_slug_raises(self):
        with pytest.raises(ValidationError):
            RefinedIdea(
                name_candidate="Test",
                slug="!@#",
                core_feature="test",
                target_user="test",
                value_proposition="test",
                category="Utilities",
                ai_capability_required="test",
            )

    def test_default_paywall_strategy(self):
        idea = RefinedIdea(
            name_candidate="Test",
            slug="test",
            core_feature="test",
            target_user="test",
            value_proposition="test",
            category="Utilities",
            ai_capability_required="test",
        )
        assert PaywallTier.WEEKLY in idea.paywall_strategy
        assert PaywallTier.YEARLY in idea.paywall_strategy


class TestKeywordOpportunity:
    def test_opportunity_score_computed(self):
        kw = KeywordOpportunity(
            term="stamp identifier",
            popularity_score=60.0,
            competition_score=30.0,
            app_count=5,
            opportunity_score=0.0,
            source="test",
        )
        # opportunity = (60/100)*0.6 - (30/100)*0.4 = 0.36 - 0.12 = 0.24
        assert kw.opportunity_score == pytest.approx(0.24, abs=0.01)

    def test_popularity_score_bounds(self):
        with pytest.raises(ValidationError):
            KeywordOpportunity(
                term="test",
                popularity_score=101.0,
                competition_score=50.0,
                app_count=0,
                opportunity_score=0.0,
            )

    def test_negative_competition_raises(self):
        with pytest.raises(ValidationError):
            KeywordOpportunity(
                term="test",
                popularity_score=50.0,
                competition_score=-1.0,
                app_count=0,
                opportunity_score=0.0,
            )


class TestKeywordResearchResult:
    def test_keyword_string_over_100_chars_raises(self, keyword_result):
        with pytest.raises(ValidationError):
            KeywordResearchResult(
                seed_keyword="test",
                primary_keyword=keyword_result.primary_keyword,
                supporting_keywords=[],
                keyword_string="a" * 101,
                rationale="test",
            )

    def test_keyword_string_exactly_100_chars_ok(self, keyword_result):
        result = KeywordResearchResult(
            seed_keyword="test",
            primary_keyword=keyword_result.primary_keyword,
            supporting_keywords=[],
            keyword_string="a" * 100,
            rationale="test",
        )
        assert len(result.keyword_string) == 100


class TestAppStoreMetadata:
    def test_name_over_30_chars_raises(self):
        with pytest.raises(ValidationError):
            AppStoreMetadata(
                app_name="A" * 31,
                subtitle="Valid Subtitle",
                description="desc",
                keywords="kw",
                primary_category="Utilities",
            )

    def test_subtitle_over_30_chars_raises(self):
        with pytest.raises(ValidationError):
            AppStoreMetadata(
                app_name="Valid Name",
                subtitle="A" * 31,
                description="desc",
                keywords="kw",
                primary_category="Utilities",
            )

    def test_keywords_over_100_chars_raises(self):
        with pytest.raises(ValidationError):
            AppStoreMetadata(
                app_name="Valid Name",
                subtitle="Valid Subtitle",
                description="desc",
                keywords="k" * 101,
                primary_category="Utilities",
            )

    def test_valid_metadata(self, sample_metadata):
        assert len(sample_metadata.app_name) <= 30
        assert len(sample_metadata.subtitle) <= 30
        assert len(sample_metadata.keywords) <= 100

    def test_default_age_rating(self):
        meta = AppStoreMetadata(
            app_name="Test App",
            subtitle="Test Subtitle",
            description="desc",
            keywords="test",
            primary_category="Utilities",
        )
        assert meta.age_rating == "4+"
