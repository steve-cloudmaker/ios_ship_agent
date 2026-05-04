"""
ASOResearchAgent

Scrapes competitor app data using the iTunes Search API and App Store
to understand the competitive landscape:
- Top competing apps for the target keyword
- Their ratings, descriptions, paywall patterns
- Common value propositions in screenshots
- Market gaps to differentiate against

This intel feeds into:
- VisualAgent (screenshot messaging)
- MetadataAgent (onboarding titles, paywall copy)
- AppBuilderAgent (feature priorities)
"""

from __future__ import annotations

import time
from urllib.parse import urlencode

import requests

from ios_ship_agent.agents.base_agent import BaseAgent
from ios_ship_agent.core.config import settings
from ios_ship_agent.core.models import (
    ASOResearchResult,
    CompetitorApp,
    KeywordResearchResult,
    RefinedIdea,
)
from ios_ship_agent.core.retry import retry


_ANALYSIS_SYSTEM = """You are an App Store Optimization (ASO) and product strategy expert.
You analyze competitor apps to help indie developers build better, more differentiated products."""

_ANALYSIS_PROMPT = """
We are building: {app_name}
Core feature: {core_feature}
Target keyword: {keyword}

Here are the top competitor apps we scraped:

{competitors_json}

Analyze these competitors and return a JSON object with:
{{
  "common_value_props": [
    "<Value proposition that appears in 2+ competitors>",
    ...
  ],
  "screenshot_themes": [
    "<Common screenshot messaging pattern, e.g. 'Instant identification results'>",
    ...
  ],
  "paywall_patterns": [
    "<Common paywall title format, e.g. 'Unlimited Scans'>",
    "<Common paywall title format, e.g. 'Access Full History'>",
    "<Common paywall title format, e.g. 'Expert AI Analysis'>",
    "<Common paywall title format, e.g. 'Ad-Free Experience'>",
  ],
  "market_gaps": [
    "<Something competitors are NOT doing well that we could win on>",
    ...
  ]
}}

Rules:
- Be specific and actionable
- paywall_patterns should be 4 items — the 4 bullet points on our paywall screen
- market_gaps should identify real opportunities, not generic platitudes
- screenshot_themes should be 5 items — one per screenshot
"""


class ASOResearchAgent(BaseAgent):
    """Scrapes competitor apps and identifies market opportunities."""

    name = "ASOResearchAgent"

    def __init__(self) -> None:
        super().__init__()
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": settings.SCRAPER_USER_AGENT})

    def run(
        self,
        refined_idea: RefinedIdea,
        keyword_result: KeywordResearchResult,
    ) -> ASOResearchResult:
        """
        Args:
            refined_idea: Output from IdeaAgent
            keyword_result: Output from KeywordAgent

        Returns:
            ASOResearchResult with competitor intel and market gaps
        """
        keyword = keyword_result.primary_keyword.term
        self.logger.info(f"Researching competitors for keyword: '{keyword}'")

        if settings.DRY_RUN:
            return self._dry_run_result(keyword)

        apps = self._search_apps(keyword)
        self.logger.info(f"Found {len(apps)} competitor apps")

        if not apps:
            # Fallback to category search
            apps = self._search_apps(refined_idea.category.lower())
            self.logger.info(f"Category fallback: found {len(apps)} apps")

        competitors = self._fetch_details(apps)
        self.logger.info(f"Fetched details for {len(competitors)} competitors")

        if not competitors:
            self.logger.warning("No competitor data — using Claude to synthesize from scratch")
            return self._synthesize_without_competitors(refined_idea, keyword)

        analysis = self._analyze_competitors(
            competitors=competitors,
            refined_idea=refined_idea,
            keyword=keyword,
        )

        top = max(competitors, key=lambda a: a.rating_count) if competitors else None

        return ASOResearchResult(
            keyword=keyword,
            competitors=competitors,
            top_competitor=top,
            common_value_props=analysis.get("common_value_props", []),
            screenshot_themes=analysis.get("screenshot_themes", []),
            paywall_patterns=analysis.get("paywall_patterns", []),
            market_gaps=analysis.get("market_gaps", []),
        )

    # ------------------------------------------------------------------
    # Scrapers
    # ------------------------------------------------------------------

    @retry(max_attempts=3, base_delay=1.5, exceptions=(requests.RequestException,))
    def _search_apps(self, term: str, limit: int = 10) -> list[dict]:
        """Search iTunes for apps matching a term."""
        params = {
            "term": term,
            "country": "us",
            "media": "software",
            "entity": "software",
            "limit": str(limit),
        }
        url = f"{settings.ITUNES_SEARCH_API}?{urlencode(params)}"

        try:
            resp = self._session.get(url, timeout=settings.SCRAPER_TIMEOUT_SECONDS)
            resp.raise_for_status()
            data = resp.json()
            time.sleep(settings.SCRAPER_DELAY_SECONDS)
            return data.get("results", [])
        except Exception as exc:
            self.logger.warning(f"App search failed for '{term}': {exc}")
            return []

    @retry(max_attempts=3, base_delay=1.5, exceptions=(requests.RequestException,))
    def _lookup_app(self, app_id: str) -> dict | None:
        """Look up detailed app info by ID."""
        params = {"id": app_id, "country": "us"}
        url = f"{settings.ITUNES_LOOKUP_API}?{urlencode(params)}"

        try:
            resp = self._session.get(url, timeout=settings.SCRAPER_TIMEOUT_SECONDS)
            resp.raise_for_status()
            results = resp.json().get("results", [])
            time.sleep(settings.SCRAPER_DELAY_SECONDS)
            return results[0] if results else None
        except Exception as exc:
            self.logger.debug(f"Lookup failed for app_id={app_id}: {exc}")
            return None

    def _fetch_details(self, raw_apps: list[dict]) -> list[CompetitorApp]:
        """Convert raw iTunes results to CompetitorApp objects."""
        competitors: list[CompetitorApp] = []

        for raw in raw_apps[:8]:  # cap at 8 competitors
            try:
                app_id = str(raw.get("trackId", ""))
                if not app_id:
                    continue

                # Guess paywall style from price + IAP
                price = float(raw.get("price", 0))
                has_iap = bool(raw.get("isGameCenterEnabled") or "In-App" in raw.get("description", ""))
                if price > 0:
                    paywall_style = "one-time"
                elif has_iap:
                    paywall_style = "subscription"
                else:
                    paywall_style = "freemium"

                screenshots = raw.get("screenshotUrls", [])

                competitor = CompetitorApp(
                    app_id=app_id,
                    name=raw.get("trackName", ""),
                    developer=raw.get("artistName", ""),
                    rating=float(raw.get("averageUserRating", 0)),
                    rating_count=int(raw.get("userRatingCount", 0)),
                    price=price,
                    has_iap=has_iap,
                    description=raw.get("description", "")[:1000],
                    subtitle=raw.get("subtitle", None),
                    screenshot_urls=screenshots[:5],
                    icon_url=raw.get("artworkUrl512", None),
                    release_date=raw.get("releaseDate", None),
                    category=raw.get("primaryGenreName", None),
                    paywall_style_guess=paywall_style,
                )
                competitors.append(competitor)

            except Exception as exc:
                self.logger.debug(f"Skipping malformed competitor: {exc}")

        return competitors

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def _analyze_competitors(
        self,
        competitors: list[CompetitorApp],
        refined_idea: RefinedIdea,
        keyword: str,
    ) -> dict:
        """Use Claude to analyze competitor data and identify patterns."""
        import json

        competitors_data = [
            {
                "name": c.name,
                "rating": c.rating,
                "rating_count": c.rating_count,
                "paywall_style": c.paywall_style_guess,
                "description_excerpt": c.description[:300],
                "subtitle": c.subtitle,
            }
            for c in competitors
        ]

        return self._ask_claude_json(
            prompt=_ANALYSIS_PROMPT.format(
                app_name=refined_idea.name_candidate,
                core_feature=refined_idea.core_feature,
                keyword=keyword,
                competitors_json=json.dumps(competitors_data, indent=2),
            ),
            system=_ANALYSIS_SYSTEM,
        )

    def _synthesize_without_competitors(
        self, refined_idea: RefinedIdea, keyword: str
    ) -> ASOResearchResult:
        """When no competitor data is available, synthesize from Claude's knowledge."""
        import json

        data = self._ask_claude_json(
            prompt=f"""
We're building an iOS app: {refined_idea.name_candidate}
Core feature: {refined_idea.core_feature}
Target keyword: {keyword}

No competitor data was found. Based on your knowledge of the App Store ecosystem,
synthesize plausible ASO data for this category.

Return JSON:
{{
  "common_value_props": ["<value prop>", ...],
  "screenshot_themes": ["<theme>", "<theme>", "<theme>", "<theme>", "<theme>"],
  "paywall_patterns": ["<paywall title>", "<paywall title>", "<paywall title>", "<paywall title>"],
  "market_gaps": ["<gap>", ...]
}}
""",
            system=_ANALYSIS_SYSTEM,
        )

        return ASOResearchResult(
            keyword=keyword,
            competitors=[],
            top_competitor=None,
            common_value_props=data.get("common_value_props", []),
            screenshot_themes=data.get("screenshot_themes", []),
            paywall_patterns=data.get("paywall_patterns", []),
            market_gaps=data.get("market_gaps", []),
        )

    # ------------------------------------------------------------------
    # Dry run
    # ------------------------------------------------------------------

    def _dry_run_result(self, keyword: str) -> ASOResearchResult:
        self.logger.info("DRY RUN: returning fixture ASO data")
        return ASOResearchResult(
            keyword=keyword,
            competitors=[],
            top_competitor=None,
            common_value_props=[
                "Instant AI-powered identification",
                "Build and track your collection",
                "Discover the value of your items",
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
                "Most competitors have poor collection management UI",
                "No app offers real-time market value estimates",
            ],
        )
