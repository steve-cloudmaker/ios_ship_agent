"""
Shared test fixtures for ios_ship_agent tests.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Set test env vars BEFORE any ios_ship_agent import
os.environ.setdefault("ANTHROPIC_API_KEY", "test-anthropic-key")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("DRY_RUN", "false")
os.environ.setdefault("SKIP_BUILD", "true")
os.environ.setdefault("LOG_LEVEL", "WARNING")  # quiet during tests


from ios_ship_agent.core.models import (
    ASOResearchResult,
    AppIdea,
    AppStoreMetadata,
    CompetitorApp,
    KeywordOpportunity,
    KeywordResearchResult,
    PaywallTier,
    RefinedIdea,
    VisualResult,
    IconAsset,
    Screenshot,
)


# ---------------------------------------------------------------------------
# Fixture: RefinedIdea
# ---------------------------------------------------------------------------

@pytest.fixture
def stamp_idea() -> AppIdea:
    return AppIdea(raw_input="An app that identifies postage stamps and tells you their value")


@pytest.fixture
def refined_stamp() -> RefinedIdea:
    return RefinedIdea(
        name_candidate="Stamp Identifier",
        slug="stamp-identifier",
        core_feature="Scan a postage stamp with the camera to get AI-powered value and history",
        target_user="Stamp collectors and philatelists",
        value_proposition="Know what your stamps are worth instantly without consulting a dealer",
        category="Utilities",
        ai_capability_required="Visual object recognition for postage stamps via camera",
        paywall_strategy=[PaywallTier.WEEKLY, PaywallTier.YEARLY],
        is_single_use=False,
    )


# ---------------------------------------------------------------------------
# Fixture: KeywordResearchResult
# ---------------------------------------------------------------------------

@pytest.fixture
def keyword_result(refined_stamp: RefinedIdea) -> KeywordResearchResult:
    primary = KeywordOpportunity(
        term="stamp identifier",
        popularity_score=62.0,
        competition_score=35.0,
        app_count=4,
        opportunity_score=0.233,
        source="scraper",
    )
    supporting = [
        KeywordOpportunity(
            term="stamp value",
            popularity_score=55.0,
            competition_score=30.0,
            app_count=8,
            opportunity_score=0.21,
            source="scraper",
        ),
        KeywordOpportunity(
            term="philately",
            popularity_score=40.0,
            competition_score=20.0,
            app_count=3,
            opportunity_score=0.16,
            source="scraper",
        ),
    ]
    return KeywordResearchResult(
        seed_keyword="stamp identifier",
        primary_keyword=primary,
        supporting_keywords=supporting,
        keyword_string="stamp,philately,postage,collector,antique,coins,value,appraisal",
        rationale="'stamp identifier' has the best opportunity score with few competitors.",
    )


# ---------------------------------------------------------------------------
# Fixture: ASOResearchResult
# ---------------------------------------------------------------------------

@pytest.fixture
def aso_result() -> ASOResearchResult:
    competitor = CompetitorApp(
        app_id="123456789",
        name="StampScan Pro",
        developer="Indie Dev Co",
        rating=4.2,
        rating_count=312,
        price=0.0,
        has_iap=True,
        description="Scan and identify your stamps with AI. Get instant value estimates.",
        subtitle="AI Stamp Scanner",
        screenshot_urls=[],
        paywall_style_guess="subscription",
    )
    return ASOResearchResult(
        keyword="stamp identifier",
        competitors=[competitor],
        top_competitor=competitor,
        common_value_props=[
            "Instant AI identification",
            "Track your collection value",
        ],
        screenshot_themes=[
            "Point. Scan. Identify instantly.",
            "Know exactly what it's worth",
            "Your collection, beautifully organized",
            "History at a glance",
            "Trusted by collectors worldwide",
        ],
        paywall_patterns=[
            "Unlimited Scans",
            "Full Collection History",
            "Expert AI Analysis",
            "Ad-Free Experience",
        ],
        market_gaps=[
            "No competitor shows real-time auction prices",
            "Collection UI is poor across all competitors",
        ],
    )


# ---------------------------------------------------------------------------
# Fixture: AppStoreMetadata
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_metadata() -> AppStoreMetadata:
    return AppStoreMetadata(
        app_name="Stamp Identifier",
        subtitle="AI Stamp Scanner & Value",
        description=(
            "Discover the hidden value in your stamp collection. Point your camera at any "
            "postage stamp and get instant AI-powered identification, value estimates, and "
            "fascinating historical context.\n\n"
            "Whether you're a lifelong philatelist or just found grandma's old albums, "
            "Stamp Identifier makes it easy to know what you have and what it's worth."
        ),
        keywords="stamp,philately,postage,collector,antique,coins,value,appraisal",
        promotional_text="New: Real-time auction price tracking!",
        primary_category="Utilities",
        age_rating="4+",
        onboarding_titles=[
            "Scan Any Stamp Instantly",
            "Discover Its True Value",
            "Build Your Collection",
        ],
        paywall_titles=[
            "Unlimited Scans",
            "Full Collection History",
            "Expert AI Analysis",
            "Ad-Free Experience",
        ],
        screenshot_headlines=[
            "Point. Scan. Identify.",
            "Know What It's Worth",
            "Your Collection, Organized",
            "History at a Glance",
            "Trusted by Collectors",
        ],
    )


# ---------------------------------------------------------------------------
# Fixture: VisualResult (stub paths)
# ---------------------------------------------------------------------------

@pytest.fixture
def visual_result(tmp_path: Path) -> VisualResult:
    icon_path = tmp_path / "AppIcon.png"

    # Create a minimal 1x1 PNG
    from PIL import Image
    img = Image.new("RGB", (1024, 1024), (75, 70, 229))
    img.save(icon_path)

    screenshots = []
    for i in range(5):
        ss_path = tmp_path / f"screenshot_{i+1:02d}.png"
        img = Image.new("RGB", (1320, 2868), (75, 70, 229))
        img.save(ss_path)
        screenshots.append(
            Screenshot(
                path=ss_path,
                width=1320,
                height=2868,
                headline=f"Screenshot {i+1}",
                subheadline="",
                device_frame=False,
                sequence=i + 1,
            )
        )

    return VisualResult(
        icon=IconAsset(
            source_path=icon_path,
            variant_paths={},
            dalle_prompt="A magnifying glass over a postage stamp",
            accent_color_hex="#4B46E5",
        ),
        screenshots=screenshots,
        accent_color_hex="#4B46E5",
        color_palette=["#4B46E5", "#FFFFFF", "#1F2937"],
    )


# ---------------------------------------------------------------------------
# Mock: Anthropic Claude
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_claude():
    """Mock Anthropic client so no real API calls are made."""
    with patch("anthropic.Anthropic") as MockAnthropic:
        mock_client = MagicMock()
        MockAnthropic.return_value = mock_client

        # Default response
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"test": true}')]
        mock_client.messages.create.return_value = mock_response

        yield mock_client


# ---------------------------------------------------------------------------
# Pytest option: --run-integration
# ---------------------------------------------------------------------------

def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests (requires real API keys)",
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if not config.getoption("--run-integration"):
        skip_integration = pytest.mark.skip(reason="Pass --run-integration to run")
        for item in items:
            if "integration" in str(item.fspath):
                item.add_marker(skip_integration)
