"""
Core data models for the iOS Ship Agent pipeline.
All inter-agent data is typed and validated via Pydantic.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class PaywallTier(str, Enum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"
    LIFETIME = "lifetime"


class AgentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class ASOProvider(str, Enum):
    SCRAPER = "scraper"
    ASTRO = "astro"
    APPFOLLOW = "appfollow"
    APPTWEAK = "apptweak"


# ---------------------------------------------------------------------------
# Idea Stage
# ---------------------------------------------------------------------------


class AppIdea(BaseModel):
    """Raw user input."""

    raw_input: str = Field(..., description="The user's original app idea string")
    submitted_at: datetime = Field(default_factory=datetime.utcnow)


class RefinedIdea(BaseModel):
    """IdeaAgent output — a validated, structured app concept."""

    name_candidate: str = Field(..., description="Working title for the app")
    slug: str = Field(..., description="URL-safe slug, e.g. 'stamp-identifier'")
    core_feature: str = Field(..., description="One-sentence description of the main feature")
    target_user: str = Field(..., description="Who this app is for")
    value_proposition: str = Field(..., description="Why a user would pay for this")
    category: str = Field(..., description="Primary App Store category")
    ai_capability_required: str = Field(..., description="The AI/vision capability needed")
    paywall_strategy: list[PaywallTier] = Field(
        default=[PaywallTier.WEEKLY, PaywallTier.YEARLY],
        description="Recommended paywall tiers",
    )
    is_single_use: bool = Field(
        default=False,
        description="If true, prefer lifetime over yearly subscription",
    )

    @field_validator("slug")
    @classmethod
    def slug_is_valid(cls, v: str) -> str:
        import re
        v = re.sub(r"[^a-z0-9-]", "", v.lower().replace(" ", "-"))
        if not v:
            raise ValueError("Slug must contain at least one alphanumeric character")
        return v


# ---------------------------------------------------------------------------
# Keyword Stage
# ---------------------------------------------------------------------------


class KeywordOpportunity(BaseModel):
    """A single keyword with scoring."""

    term: str
    popularity_score: float = Field(ge=0, le=100, description="0-100 popularity proxy")
    competition_score: float = Field(ge=0, le=100, description="0-100 competition estimate")
    app_count: int = Field(ge=0, description="Number of apps ranking for this keyword")
    opportunity_score: float = Field(
        ge=0, le=1, description="Composite score: high popularity, low competition"
    )
    source: str = Field(default="scraper", description="Where this keyword came from")

    @model_validator(mode="after")
    def compute_opportunity(self) -> KeywordOpportunity:
        if self.opportunity_score == 0:
            from ios_ship_agent.core.config import settings
            self.opportunity_score = round(
                (self.popularity_score / 100) * settings.KEYWORD_POPULARITY_WEIGHT
                - (self.competition_score / 100) * settings.KEYWORD_COMPETITION_WEIGHT,
                4,
            )
        return self


class KeywordResearchResult(BaseModel):
    """KeywordAgent output."""

    seed_keyword: str
    primary_keyword: KeywordOpportunity = Field(
        ..., description="Best keyword to target as app name/subtitle"
    )
    supporting_keywords: list[KeywordOpportunity] = Field(
        default_factory=list,
        description="Additional keywords for keyword field & description",
    )
    keyword_string: str = Field(
        ...,
        description="100-char App Store keyword field string (comma-separated, no spaces after commas)",
    )
    rationale: str = Field(..., description="Why the primary keyword was chosen")

    @field_validator("keyword_string")
    @classmethod
    def keyword_string_fits(cls, v: str) -> str:
        if len(v) > 100:
            raise ValueError(f"keyword_string must be ≤ 100 chars, got {len(v)}")
        return v


# ---------------------------------------------------------------------------
# ASO Research Stage
# ---------------------------------------------------------------------------


class CompetitorApp(BaseModel):
    """Scraped competitor app data."""

    app_id: str
    name: str
    developer: str
    rating: float = Field(ge=0, le=5)
    rating_count: int
    price: float
    has_iap: bool
    description: str
    subtitle: str | None = None
    keywords_visible: list[str] = Field(default_factory=list)
    screenshot_urls: list[str] = Field(default_factory=list)
    icon_url: str | None = None
    release_date: str | None = None
    category: str | None = None
    paywall_style_guess: str | None = None  # "subscription", "one-time", "freemium"


class ASOResearchResult(BaseModel):
    """ASOResearchAgent output."""

    keyword: str
    competitors: list[CompetitorApp] = Field(default_factory=list)
    top_competitor: CompetitorApp | None = None
    common_value_props: list[str] = Field(
        default_factory=list,
        description="Value propositions that appear across top competitors",
    )
    screenshot_themes: list[str] = Field(
        default_factory=list,
        description="Common screenshot messaging patterns",
    )
    paywall_patterns: list[str] = Field(
        default_factory=list,
        description="Common paywall title patterns",
    )
    market_gaps: list[str] = Field(
        default_factory=list,
        description="Identified gaps in current competitor offerings",
    )


# ---------------------------------------------------------------------------
# App Build Stage
# ---------------------------------------------------------------------------


class SwiftFeature(BaseModel):
    """A single feature screen to scaffold."""

    name: str  # e.g. "CameraScreen"
    description: str
    tab_icon: str = "star"  # SF Symbol name


class AppBuildSpec(BaseModel):
    """Spec sent to AppBuilderAgent."""

    app_name: str
    bundle_id: str  # e.g. "com.indie.stampidentifier"
    core_feature: str
    ai_capability: str
    screens: list[SwiftFeature]
    paywall_tiers: list[PaywallTier]
    accent_color_hex: str = "#4F46E5"
    deployment_target: str = "17.0"


class AppBuildResult(BaseModel):
    """AppBuilderAgent output."""

    project_path: Path
    bundle_id: str
    scheme_name: str
    build_succeeded: bool
    build_log: str
    claude_code_prompts: list[str] = Field(
        default_factory=list, description="Prompts sent to Claude Code"
    )
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Visual Stage
# ---------------------------------------------------------------------------


class IconAsset(BaseModel):
    """Generated icon files."""

    source_path: Path = Field(..., description="1024x1024 master icon")
    variant_paths: dict[str, Path] = Field(
        default_factory=dict,
        description="All required sizes: {'20x20@1x': Path(...), ...}",
    )
    dalle_prompt: str
    accent_color_hex: str


class Screenshot(BaseModel):
    """A single App Store screenshot."""

    path: Path
    width: int
    height: int
    headline: str
    subheadline: str
    device_frame: bool = True
    sequence: int  # 1-indexed display order


class VisualResult(BaseModel):
    """VisualAgent output."""

    icon: IconAsset
    screenshots: list[Screenshot] = Field(default_factory=list)
    accent_color_hex: str
    color_palette: list[str] = Field(
        default_factory=list, description="Full palette used in screenshots"
    )


# ---------------------------------------------------------------------------
# Metadata Stage
# ---------------------------------------------------------------------------


class AppStoreMetadata(BaseModel):
    """App Store Connect metadata — copy-paste ready."""

    app_name: str = Field(..., max_length=30)
    subtitle: str = Field(..., max_length=30)
    description: str = Field(..., max_length=4000)
    keywords: str = Field(..., max_length=100)
    promotional_text: str = Field(default="", max_length=170)
    privacy_policy_url: str = Field(default="")
    support_url: str = Field(default="")
    marketing_url: str = Field(default="")
    primary_category: str
    secondary_category: str | None = None
    age_rating: str = "4+"
    onboarding_titles: list[str] = Field(
        default_factory=list, description="3-4 onboarding screen titles"
    )
    paywall_titles: list[str] = Field(
        default_factory=list, description="4 paywall benefit bullet titles"
    )
    screenshot_headlines: list[str] = Field(
        default_factory=list, description="Headline for each screenshot"
    )

    @field_validator("app_name")
    @classmethod
    def name_length(cls, v: str) -> str:
        if len(v) > 30:
            raise ValueError(f"App name must be ≤ 30 chars, got {len(v)}: '{v}'")
        return v

    @field_validator("subtitle")
    @classmethod
    def subtitle_length(cls, v: str) -> str:
        if len(v) > 30:
            raise ValueError(f"Subtitle must be ≤ 30 chars, got {len(v)}: '{v}'")
        return v

    @field_validator("keywords")
    @classmethod
    def keywords_length(cls, v: str) -> str:
        if len(v) > 100:
            raise ValueError(f"Keywords must be ≤ 100 chars, got {len(v)}")
        return v


# ---------------------------------------------------------------------------
# Pipeline State (Orchestrator)
# ---------------------------------------------------------------------------


class AgentRun(BaseModel):
    """Execution record for a single agent."""

    agent_name: str
    status: AgentStatus = AgentStatus.PENDING
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_seconds: float | None = None
    error: str | None = None
    retries: int = 0


class PipelineResult(BaseModel):
    """Final output of the full pipeline."""

    run_id: str
    app_idea: str
    slug: str
    output_dir: Path
    started_at: datetime
    finished_at: datetime | None = None
    total_duration_seconds: float | None = None
    agent_runs: list[AgentRun] = Field(default_factory=list)

    # Per-stage outputs
    refined_idea: RefinedIdea | None = None
    keyword_research: KeywordResearchResult | None = None
    aso_research: ASOResearchResult | None = None
    app_build: AppBuildResult | None = None
    visuals: VisualResult | None = None
    metadata: AppStoreMetadata | None = None

    success: bool = False
    submission_package_path: Path | None = None
    errors: list[str] = Field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "app": self.slug,
            "success": self.success,
            "duration": f"{self.total_duration_seconds:.1f}s"
            if self.total_duration_seconds
            else "N/A",
            "output": str(self.submission_package_path) if self.submission_package_path else None,
            "agents": [
                {"name": r.agent_name, "status": r.status, "retries": r.retries}
                for r in self.agent_runs
            ],
            "errors": self.errors,
        }
