"""
KeywordAgent

Discovers App Store keyword opportunities using:
1. iTunes Search API (public, no auth required) — competitor discovery
2. App Store search suggestion API — autocomplete keywords
3. Claude — scoring, ranking, and keyword string generation

Designed to be swapped out for a real ASO provider (Astro, AppFollow, etc.)
by changing ASO_PROVIDER in settings.
"""

from __future__ import annotations

import time
from urllib.parse import urlencode

import requests

from ios_ship_agent.agents.base_agent import BaseAgent
from ios_ship_agent.core.config import settings
from ios_ship_agent.core.models import KeywordOpportunity, KeywordResearchResult, RefinedIdea
from ios_ship_agent.core.retry import retry


_SCORE_SYSTEM = """You are an App Store Optimization (ASO) expert.
You help indie iOS developers choose the best keywords to maximize organic downloads.
You understand keyword popularity, competition, and how the App Store algorithm works."""

_SCORE_PROMPT = """
App: {app_name}
Core feature: {core_feature}
Category: {category}

Candidate keywords and their raw data:
{keyword_data}

For each keyword, score:
- popularity_score: 0-100 (how often people search for this)
- competition_score: 0-100 (how hard it is to rank)

Return a JSON array:
[
  {{
    "term": "keyword",
    "popularity_score": 65,
    "competition_score": 40,
    "opportunity_score": 0.0,
    "source": "suggest"
  }},
  ...
]

Rules:
- Long-tail keywords (3+ words) have lower competition — reward them
- Generic single-word keywords have very high competition (70-95)
- If app_count > 100 and ratings are high, competition is high
- opportunity_score leave as 0.0 — it will be computed from weights
- Be realistic; don't inflate popularity
"""

_STRING_PROMPT = """
Selected keywords for App Store keyword field:
{keywords}

App name (will appear in title, do NOT repeat): {app_name}
App subtitle keywords (do NOT repeat): {subtitle_keywords}

Create a comma-separated keyword string for the App Store keyword field.
Rules:
- MAXIMUM 100 characters total (including commas)
- Do NOT use spaces after commas (saves characters)
- Do NOT repeat words already in the app name or subtitle
- Prioritize medium-competition, medium-popularity keywords
- Include category-adjacent keywords (e.g. for a stamp app: "postage,philately,coins,antique")
- Every character counts; use short forms where natural

Return ONLY the keyword string, nothing else. No quotes, no explanation.
"""


class KeywordAgent(BaseAgent):
    """Discovers and scores App Store keyword opportunities."""

    name = "KeywordAgent"

    def __init__(self) -> None:
        super().__init__()
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": settings.SCRAPER_USER_AGENT})

    def run(self, refined_idea: RefinedIdea) -> KeywordResearchResult:
        """
        Args:
            refined_idea: Output from IdeaAgent

        Returns:
            KeywordResearchResult with primary keyword and keyword string
        """
        seed = refined_idea.name_candidate.lower()
        self.logger.info(f"Keyword research starting for seed: '{seed}'")

        if settings.DRY_RUN:
            return self._dry_run_result(refined_idea)

        if settings.ASO_PROVIDER == "astro":
            return self._astro_research(refined_idea)

        # Default: scraper pipeline
        suggestions = self._fetch_suggestions(seed)
        self.logger.info(f"Got {len(suggestions)} autocomplete suggestions")

        itunes_keywords = self._fetch_itunes_keywords(seed, refined_idea.category)
        self.logger.info(f"Got {len(itunes_keywords)} iTunes keyword proxies")

        all_candidates = list(set(suggestions + itunes_keywords))[:settings.KEYWORD_MAX_RESULTS]
        self.logger.info(f"Scoring {len(all_candidates)} total candidate keywords")

        scored = self._score_keywords(
            keywords=all_candidates,
            refined_idea=refined_idea,
        )

        # Filter by minimum score
        viable = [k for k in scored if k.opportunity_score >= settings.KEYWORD_MIN_SCORE]
        if not viable:
            viable = scored[:5]  # fallback: just take the top 5

        viable.sort(key=lambda k: k.opportunity_score, reverse=True)

        primary = viable[0]
        supporting = viable[1 : settings.KEYWORD_TARGET_COUNT + 1]

        self.logger.info(
            f"Primary keyword: '{primary.term}' "
            f"(opportunity={primary.opportunity_score:.3f})"
        )

        keyword_string = self._build_keyword_string(
            primary=primary,
            supporting=supporting,
            app_name=refined_idea.name_candidate,
        )

        self.logger.info(f"Keyword string ({len(keyword_string)} chars): {keyword_string}")

        return KeywordResearchResult(
            seed_keyword=seed,
            primary_keyword=primary,
            supporting_keywords=supporting,
            keyword_string=keyword_string,
            rationale=f"'{primary.term}' has the best opportunity score ({primary.opportunity_score:.3f}). "
            f"Competition is manageable with {primary.app_count} competing apps. "
            f"Supporting keywords broaden the reach without cannibalizing the primary.",
        )

    # ------------------------------------------------------------------
    # Scrapers
    # ------------------------------------------------------------------

    @retry(max_attempts=3, base_delay=1.5, exceptions=(requests.RequestException,))
    def _fetch_suggestions(self, term: str) -> list[str]:
        """
        Fetch autocomplete suggestions from the App Store search hint API.
        This is the same endpoint the App Store uses when you type in the search bar.
        """
        params = {
            "media": "software",
            "term": term,
            "limit": "25",
            "country": "us",
            "lang": "en_us",
        }
        url = f"{settings.APP_STORE_SUGGEST_URL}?{urlencode(params)}"

        try:
            resp = self._session.get(url, timeout=settings.SCRAPER_TIMEOUT_SECONDS)
            resp.raise_for_status()
            data = resp.json()
            terms: list[str] = []
            for entry in data.get("hints", []):
                if isinstance(entry, dict) and "term" in entry:
                    terms.append(entry["term"].lower().strip())
                elif isinstance(entry, str):
                    terms.append(entry.lower().strip())
            return terms
        except Exception as exc:
            self.logger.warning(f"Suggest API failed for '{term}': {exc}")
            return []

    @retry(max_attempts=3, base_delay=1.5, exceptions=(requests.RequestException,))
    def _fetch_itunes_keywords(self, term: str, category: str) -> list[str]:
        """
        Use the iTunes Search API to find apps matching the term,
        then extract keyword signals from app names, subtitles, and descriptions.

        The iTunes Search API is completely public and does not require any API key.
        """
        params = {
            "term": term,
            "country": "us",
            "media": "software",
            "entity": "software",
            "limit": "20",
            "lang": "en_us",
        }
        url = f"{settings.ITUNES_SEARCH_API}?{urlencode(params)}"

        try:
            resp = self._session.get(url, timeout=settings.SCRAPER_TIMEOUT_SECONDS)
            resp.raise_for_status()
            data = resp.json()

            keywords: list[str] = []
            for result in data.get("results", []):
                # Pull keywords from app name
                app_name: str = result.get("trackName", "")
                if app_name:
                    words = app_name.lower().split()
                    if 2 <= len(words) <= 5:
                        keywords.append(app_name.lower())
                    for word in words:
                        if len(word) > 4:
                            keywords.append(word)

                # Description keywords (first 200 chars)
                desc: str = result.get("description", "")[:200]
                desc_words = [w.lower().strip(".,!?") for w in desc.split() if len(w) > 5]
                keywords.extend(desc_words[:10])

            # Deduplicate and filter
            seen: set[str] = set()
            unique: list[str] = []
            for kw in keywords:
                kw = kw.strip()
                if kw and kw not in seen and len(kw) > 3:
                    seen.add(kw)
                    unique.append(kw)

            time.sleep(settings.SCRAPER_DELAY_SECONDS)
            return unique[:30]

        except Exception as exc:
            self.logger.warning(f"iTunes keyword fetch failed for '{term}': {exc}")
            return []

    # ------------------------------------------------------------------
    # Scoring via Claude
    # ------------------------------------------------------------------

    def _score_keywords(
        self, keywords: list[str], refined_idea: RefinedIdea
    ) -> list[KeywordOpportunity]:
        """Ask Claude to score keyword candidates."""

        keyword_data = "\n".join(f"- {kw}" for kw in keywords)

        raw = self._ask_claude_json(
            prompt=_SCORE_PROMPT.format(
                app_name=refined_idea.name_candidate,
                core_feature=refined_idea.core_feature,
                category=refined_idea.category,
                keyword_data=keyword_data,
            ),
            system=_SCORE_SYSTEM,
        )

        results: list[KeywordOpportunity] = []

        if isinstance(raw, list):
            items = raw
        elif isinstance(raw, dict) and "keywords" in raw:
            items = raw["keywords"]
        else:
            self.logger.warning(f"Unexpected keyword score format: {type(raw)}")
            return self._fallback_scores(keywords)

        for item in items:
            try:
                opp = KeywordOpportunity(
                    term=item["term"],
                    popularity_score=float(item.get("popularity_score", 50)),
                    competition_score=float(item.get("competition_score", 50)),
                    app_count=int(item.get("app_count", 0)),
                    opportunity_score=0.0,  # computed in model validator
                    source=item.get("source", "scored"),
                )
                results.append(opp)
            except Exception as exc:
                self.logger.debug(f"Skipping malformed keyword item: {item} — {exc}")

        return results

    def _fallback_scores(self, keywords: list[str]) -> list[KeywordOpportunity]:
        """Simple heuristic scoring if Claude fails."""
        results = []
        for i, kw in enumerate(keywords):
            word_count = len(kw.split())
            # Long-tail = lower competition
            comp = max(20, 80 - word_count * 15)
            pop = max(20, 70 - i * 2)
            results.append(
                KeywordOpportunity(
                    term=kw,
                    popularity_score=pop,
                    competition_score=comp,
                    app_count=0,
                    opportunity_score=0.0,
                    source="fallback",
                )
            )
        return results

    def _build_keyword_string(
        self,
        primary: KeywordOpportunity,
        supporting: list[KeywordOpportunity],
        app_name: str,
    ) -> str:
        """Ask Claude to build the optimal 100-char keyword string."""
        all_terms = [primary.term] + [k.term for k in supporting]
        subtitle_keywords = primary.term.split()

        raw = self._ask_claude(
            prompt=_STRING_PROMPT.format(
                keywords="\n".join(f"- {t}" for t in all_terms),
                app_name=app_name,
                subtitle_keywords=",".join(subtitle_keywords),
            ),
            system=_SCORE_SYSTEM,
        )

        # Clean up
        result = raw.strip().strip('"').strip("'")

        # Hard enforce 100-char limit
        if len(result) > 100:
            # Trim trailing incomplete keyword
            result = result[:100].rsplit(",", 1)[0]

        return result

    # ------------------------------------------------------------------
    # ASO provider stubs
    # ------------------------------------------------------------------

    def _astro_research(self, refined_idea: RefinedIdea) -> KeywordResearchResult:
        """Placeholder for Astro ASO integration."""
        raise NotImplementedError(
            "Astro ASO integration not yet implemented. "
            "Set ASO_PROVIDER=scraper or implement _astro_research()."
        )

    def _dry_run_result(self, refined_idea: RefinedIdea) -> KeywordResearchResult:
        """Return fixture data in dry-run mode."""
        self.logger.info("DRY RUN: returning fixture keyword data")
        primary = KeywordOpportunity(
            term=f"{refined_idea.slug.replace('-', ' ')}",
            popularity_score=62.0,
            competition_score=38.0,
            app_count=4,
            opportunity_score=0.0,
            source="dry_run",
        )
        return KeywordResearchResult(
            seed_keyword=refined_idea.name_candidate.lower(),
            primary_keyword=primary,
            supporting_keywords=[],
            keyword_string=f"{refined_idea.slug.replace('-', ',')},scanner,identifier",
            rationale="Dry run fixture data.",
        )
