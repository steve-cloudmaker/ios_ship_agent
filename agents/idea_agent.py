"""
IdeaAgent

Takes a raw app idea string and uses Claude to:
1. Validate the concept is viable as an iOS app
2. Identify the core AI/vision capability required
3. Choose a paywall strategy (subscription vs. lifetime)
4. Produce a structured RefinedIdea ready for the keyword pipeline
"""

from __future__ import annotations

from ios_ship_agent.agents.base_agent import BaseAgent
from ios_ship_agent.core.models import AppIdea, PaywallTier, RefinedIdea


_SYSTEM = """You are an expert iOS indie developer and product strategist.
You help solo developers ship profitable apps to the App Store.
You understand App Store Optimization, monetization, and what makes apps
succeed in a crowded market.

Your task is to take a raw app idea and produce a structured JSON spec.
Be concise, realistic, and commercially minded."""

_PROMPT_TEMPLATE = """
App idea: "{raw_idea}"

Produce a JSON object with exactly these keys:

{{
  "name_candidate": "<Working title for the app, 2-4 words>",
  "slug": "<URL-safe lowercase slug, hyphens, no spaces>",
  "core_feature": "<One sentence describing the single main feature>",
  "target_user": "<Who this is for, 1 sentence>",
  "value_proposition": "<Why someone would pay for this, 1 sentence>",
  "category": "<Primary App Store category e.g. 'Utilities', 'Photo & Video', 'Education'>",
  "ai_capability_required": "<The AI/ML/vision capability needed e.g. 'object recognition via camera', 'text extraction (OCR)', 'conversational AI'>",
  "paywall_tiers": ["weekly", "yearly"],
  "is_single_use": false,
  "viability_score": 0.85,
  "viability_notes": "<2-3 sentences on why this will or won't work>"
}}

Rules:
- paywall_tiers must be an array containing any of: "weekly", "monthly", "yearly", "lifetime"
- If the app is single-use (user does it once or twice ever), set is_single_use=true and
  use ["lifetime"] for paywall_tiers
- viability_score is a float 0.0-1.0 (be honest; below 0.5 means warn the user)
- Keep name_candidate to 2-4 words, clean, brandable
- slug must be lowercase letters, numbers, hyphens only
"""


class IdeaAgent(BaseAgent):
    """Validates and structures the raw app idea."""

    name = "IdeaAgent"

    def run(self, idea: AppIdea) -> RefinedIdea:
        """
        Args:
            idea: Raw AppIdea from user input

        Returns:
            RefinedIdea with structured fields ready for the pipeline
        """
        self.logger.info(f"Refining idea: '{idea.raw_input}'")

        data = self._ask_claude_json(
            prompt=_PROMPT_TEMPLATE.format(raw_idea=idea.raw_input),
            system=_SYSTEM,
        )

        viability_score = data.get("viability_score", 1.0)
        viability_notes = data.get("viability_notes", "")

        if viability_score < 0.5:
            self.logger.warning(
                f"Low viability score ({viability_score:.2f}): {viability_notes}"
            )
        else:
            self.logger.info(
                f"Viability score: {viability_score:.2f} — {viability_notes}"
            )

        tiers_raw: list[str] = data.get("paywall_tiers", ["weekly", "yearly"])
        tiers = [PaywallTier(t) for t in tiers_raw if t in PaywallTier.__members__.values()]
        if not tiers:
            tiers = [PaywallTier.WEEKLY, PaywallTier.YEARLY]

        refined = RefinedIdea(
            name_candidate=data["name_candidate"],
            slug=data["slug"],
            core_feature=data["core_feature"],
            target_user=data["target_user"],
            value_proposition=data["value_proposition"],
            category=data["category"],
            ai_capability_required=data["ai_capability_required"],
            paywall_strategy=tiers,
            is_single_use=bool(data.get("is_single_use", False)),
        )

        self.logger.info(
            f"Refined: '{refined.name_candidate}' "
            f"[{refined.category}] "
            f"paywall={[t.value for t in refined.paywall_strategy]}"
        )

        return refined
