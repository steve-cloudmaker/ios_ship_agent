"""
Central configuration for ios_ship_agent.
All values are overridable via environment variables or .env file.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -----------------------------------------------------------------------
    # API Keys
    # -----------------------------------------------------------------------
    ANTHROPIC_API_KEY: str = Field(..., description="Anthropic API key")
    OPENAI_API_KEY: str = Field(..., description="OpenAI API key (for DALL-E)")

    # -----------------------------------------------------------------------
    # Claude / LLM
    # -----------------------------------------------------------------------
    CLAUDE_MODEL: str = "claude-sonnet-4-20250514"
    CLAUDE_MAX_TOKENS: int = 4096
    CLAUDE_CODE_TIMEOUT_SECONDS: int = 600  # 10 min for app build

    # -----------------------------------------------------------------------
    # DALL-E
    # -----------------------------------------------------------------------
    DALLE_MODEL: str = "dall-e-3"
    DALLE_ICON_SIZE: str = "1024x1024"
    DALLE_ICON_QUALITY: str = "hd"
    DALLE_SCREENSHOT_SIZE: str = "1024x1792"  # closest to 9:19.5
    DALLE_SCREENSHOT_QUALITY: str = "standard"

    # -----------------------------------------------------------------------
    # ASO Provider
    # -----------------------------------------------------------------------
    ASO_PROVIDER: str = "scraper"  # scraper | astro | appfollow | apptweak
    ASTRO_API_KEY: str = ""
    APPFOLLOW_API_KEY: str = ""

    # -----------------------------------------------------------------------
    # Keyword Scoring
    # -----------------------------------------------------------------------
    KEYWORD_POPULARITY_WEIGHT: float = 0.6
    KEYWORD_COMPETITION_WEIGHT: float = 0.4
    KEYWORD_MIN_SCORE: float = 0.2
    KEYWORD_MAX_RESULTS: int = 30
    KEYWORD_TARGET_COUNT: int = 8  # how many to add to supporting list

    # -----------------------------------------------------------------------
    # App Store Metadata Limits
    # -----------------------------------------------------------------------
    APP_NAME_MAX: int = 30
    SUBTITLE_MAX: int = 30
    KEYWORDS_MAX: int = 100
    DESCRIPTION_MAX: int = 4000
    PROMO_TEXT_MAX: int = 170
    SCREENSHOT_COUNT: int = 5

    # -----------------------------------------------------------------------
    # Screenshot Sizes (iPhone 16 Pro Max = 6.7")
    # -----------------------------------------------------------------------
    SCREENSHOT_WIDTH: int = 1320
    SCREENSHOT_HEIGHT: int = 2868

    # -----------------------------------------------------------------------
    # iOS Icon Sizes (all required variants)
    # -----------------------------------------------------------------------
    # Format: "size@scale" -> actual pixel dimension
    ICON_SIZES: dict[str, int] = {
        "20x20@1x": 20,
        "20x20@2x": 40,
        "20x20@3x": 60,
        "29x29@1x": 29,
        "29x29@2x": 58,
        "29x29@3x": 87,
        "40x40@1x": 40,
        "40x40@2x": 80,
        "40x40@3x": 120,
        "60x60@2x": 120,
        "60x60@3x": 180,
        "76x76@1x": 76,
        "76x76@2x": 152,
        "83.5x83.5@2x": 167,
        "1024x1024@1x": 1024,
    }

    # -----------------------------------------------------------------------
    # Paywall
    # -----------------------------------------------------------------------
    DEFAULT_PAYWALL_TIERS: list[str] = ["weekly", "yearly"]
    FREE_TRIAL_DAYS: int = 3

    # -----------------------------------------------------------------------
    # Retries
    # -----------------------------------------------------------------------
    MAX_RETRIES: int = 3
    RETRY_BASE_DELAY_SECONDS: float = 2.0
    RETRY_BACKOFF_MULTIPLIER: float = 2.0

    # -----------------------------------------------------------------------
    # Output
    # -----------------------------------------------------------------------
    OUTPUT_DIR: Path = Path("output")
    LOG_LEVEL: str = "INFO"
    LOG_FILE: Path = Path("logs/ios_ship_agent.log")

    # -----------------------------------------------------------------------
    # App Store Connect (gated — only used when AUTO_SUBMIT=true)
    # -----------------------------------------------------------------------
    AUTO_SUBMIT: bool = False
    APP_STORE_CONNECT_KEY_ID: str = ""
    APP_STORE_CONNECT_ISSUER_ID: str = ""
    APP_STORE_CONNECT_KEY_PATH: Path = Path("")

    # -----------------------------------------------------------------------
    # Scraper
    # -----------------------------------------------------------------------
    SCRAPER_USER_AGENT: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    SCRAPER_DELAY_SECONDS: float = 1.5  # polite delay between requests
    SCRAPER_TIMEOUT_SECONDS: int = 15
    ITUNES_SEARCH_API: str = "https://itunes.apple.com/search"
    ITUNES_LOOKUP_API: str = "https://itunes.apple.com/lookup"
    APP_STORE_SUGGEST_URL: str = (
        "https://search.itunes.apple.com/WebObjects/MZSearchHints.woa/wa/hints"
    )

    # -----------------------------------------------------------------------
    # Dry Run / Testing
    # -----------------------------------------------------------------------
    DRY_RUN: bool = False
    SKIP_BUILD: bool = False
    FIXTURES_DIR: Path = Path("tests/fixtures")


settings = Settings()  # type: ignore[call-arg]  # loaded from env/.env
