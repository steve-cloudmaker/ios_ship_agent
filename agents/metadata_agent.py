"""
MetadataAgent

Generates all App Store Connect metadata using Claude:
- App name (≤ 30 chars) — keyword-optimized
- Subtitle (≤ 30 chars) — secondary keyword
- Description (≤ 4000 chars) — naturally keyword-stuffed
- Keywords field (≤ 100 chars) — comma-separated, no spaces
- Onboarding screen titles (3-4)
- Paywall feature titles (4)
- Screenshot headline copy (5)
- Promotional text (≤ 170 chars)

All output is validated against App Store character limits before returning.
"""

from __future__ import annotations

import re

from ios_ship_agent.agents.base_agent import BaseAgent
from ios_ship_agent.core.config import settings
from ios_ship_agent.core.models import (
    AppStoreMetadata,
    ASOResearchResult,
    KeywordResearchResult,
    RefinedIdea,
    VisualResult,
)


_SYSTEM = """You are an expert App Store copywriter and ASO specialist.
You write App Store metadata that:
1. Passes Apple's review guidelines
2. Naturally incorporates target keywords without keyword stuffing
3. Converts browsers to downloads by clearly communicating value
4. Follows all character limits exactly

You are precise about character counts. Every limit is a hard ceiling."""


_METADATA_PROMPT = """
Write complete App Store metadata for this iOS app:

App name candidate: {name_candidate}
Core feature: {core_feature}
Target user: {target_user}
Value proposition: {value_proposition}
Category: {category}
Primary keyword: {primary_keyword}
Supporting keywords: {supporting_keywords}
Competitor value props: {value_props}
Market gaps (our advantages): {market_gaps}
Paywall patterns (4 bullets): {paywall_patterns}
Screenshot themes (5 screens): {screenshot_themes}

Return a JSON object with exactly these keys:

{{
  "app_name": "<≤ 30 chars, includes primary keyword if possible>",
  "subtitle": "<≤ 30 chars, different keyword angle, compelling>",
  "description": "<≤ 4000 chars, 3-4 paragraphs, conversational, keyword-rich but natural>",
  "keywords": "<≤ 100 chars, comma-separated, NO spaces after commas, NO repeats from name/subtitle>",
  "promotional_text": "<≤ 170 chars, timely hook, can be updated without resubmit>",
  "primary_category": "<App Store category name>",
  "secondary_category": "<secondary category or null>",
  "age_rating": "4+",
  "onboarding_titles": [
    "<Screen 1 title>",
    "<Screen 2 title>",
    "<Screen 3 title>"
  ],
  "paywall_titles": [
    "<Benefit 1>",
    "<Benefit 2>",
    "<Benefit 3>",
    "<Benefit 4>"
  ],
  "screenshot_headlines": [
    "<Screenshot 1 headline ≤ 30 chars>",
    "<Screenshot 2 headline ≤ 30 chars>",
    "<Screenshot 3 headline ≤ 30 chars>",
    "<Screenshot 4 headline ≤ 30 chars>",
    "<Screenshot 5 headline ≤ 30 chars>"
  ]
}}

Critical rules:
- app_name MUST be ≤ 30 characters (count every character!)
- subtitle MUST be ≤ 30 characters
- keywords MUST be ≤ 100 characters total
- Do NOT use spaces after commas in keywords
- Do NOT repeat words in keywords that appear in app_name or subtitle
- description should start with a hook, not "Introducing" or "Welcome"
- onboarding_titles should be action-oriented ("Scan Any Stamp", "Discover Its Value")
- screenshot_headlines should be punchy, 3-6 words
"""


class MetadataAgent(BaseAgent):
    """Generates all App Store metadata copy."""

    name = "MetadataAgent"

    def run(
        self,
        refined_idea: RefinedIdea,
        keyword_result: KeywordResearchResult,
        aso_result: ASOResearchResult,
        visual_result: VisualResult | None = None,
    ) -> AppStoreMetadata:
        """
        Args:
            refined_idea: Output from IdeaAgent
            keyword_result: Output from KeywordAgent
            aso_result: Output from ASOResearchAgent
            visual_result: Optional VisualAgent output (for screenshot headlines)

        Returns:
            AppStoreMetadata — validated, ready for App Store Connect
        """
        self.logger.info(f"Generating metadata for '{refined_idea.name_candidate}'")

        raw = self._ask_claude_json(
            prompt=_METADATA_PROMPT.format(
                name_candidate=refined_idea.name_candidate,
                core_feature=refined_idea.core_feature,
                target_user=refined_idea.target_user,
                value_proposition=refined_idea.value_proposition,
                category=refined_idea.category,
                primary_keyword=keyword_result.primary_keyword.term,
                supporting_keywords=", ".join(
                    k.term for k in keyword_result.supporting_keywords[:6]
                ),
                value_props="\n".join(f"- {v}" for v in aso_result.common_value_props[:4]),
                market_gaps="\n".join(f"- {g}" for g in aso_result.market_gaps[:3]),
                paywall_patterns="\n".join(f"- {p}" for p in aso_result.paywall_patterns[:4]),
                screenshot_themes="\n".join(f"- {t}" for t in aso_result.screenshot_themes[:5]),
            ),
            system=_SYSTEM,
        )

        # Enforce limits (Claude sometimes goes over by 1-2 chars)
        app_name = self._enforce_limit(raw.get("app_name", refined_idea.name_candidate), 30)
        subtitle = self._enforce_limit(raw.get("subtitle", "AI-Powered Identifier"), 30)
        keywords = self._enforce_keywords(raw.get("keywords", keyword_result.keyword_string))
        description = self._enforce_limit(raw.get("description", ""), 4000)
        promo = self._enforce_limit(raw.get("promotional_text", ""), 170)

        metadata = AppStoreMetadata(
            app_name=app_name,
            subtitle=subtitle,
            description=description,
            keywords=keywords,
            promotional_text=promo,
            primary_category=raw.get("primary_category", refined_idea.category),
            secondary_category=raw.get("secondary_category") or None,
            age_rating=raw.get("age_rating", "4+"),
            onboarding_titles=raw.get("onboarding_titles", [])[:4],
            paywall_titles=raw.get("paywall_titles", aso_result.paywall_patterns[:4]),
            screenshot_headlines=raw.get("screenshot_headlines", aso_result.screenshot_themes[:5]),
        )

        self.logger.info(f"App name: '{metadata.app_name}' ({len(metadata.app_name)} chars)")
        self.logger.info(f"Subtitle: '{metadata.subtitle}' ({len(metadata.subtitle)} chars)")
        self.logger.info(f"Keywords: '{metadata.keywords}' ({len(metadata.keywords)} chars)")
        self.logger.info(f"Description: {len(metadata.description)} chars")

        return metadata

    # ------------------------------------------------------------------
    # Enforcement helpers
    # ------------------------------------------------------------------

    def _enforce_limit(self, text: str, max_chars: int) -> str:
        """Hard-trim to max_chars, preferring word boundaries."""
        text = text.strip()
        if len(text) <= max_chars:
            return text

        trimmed = text[:max_chars]
        # Try to end at a word boundary
        last_space = trimmed.rfind(" ")
        if last_space > max_chars * 0.7:
            trimmed = trimmed[:last_space]

        self.logger.warning(
            f"Trimmed text from {len(text)} to {len(trimmed)} chars "
            f"(limit: {max_chars})"
        )
        return trimmed

    def _enforce_keywords(self, keywords: str) -> str:
        """
        Ensure the keyword string is ≤ 100 chars with no spaces after commas.
        Strips terms from the end until it fits.
        """
        # Normalize: remove spaces after commas
        keywords = re.sub(r",\s+", ",", keywords.strip())

        if len(keywords) <= 100:
            return keywords

        # Trim from the end
        parts = keywords.split(",")
        result = ""
        for part in parts:
            candidate = result + ("," if result else "") + part
            if len(candidate) <= 100:
                result = candidate
            else:
                break

        self.logger.warning(
            f"Keyword string trimmed from {len(keywords)} to {len(result)} chars"
        )
        return result
