# Upgrading to a Real ASO Provider

## Current Approach

By default, `ios_ship_agent` scrapes publicly available data:

- **App Store search suggestions** — the autocomplete API used by the App Store itself
- **iTunes Search API** — public, no authentication, returns app metadata

This is free and works surprisingly well for finding keyword opportunities, but it has limitations:
- No real search volume numbers (only popularity proxies)
- No historical keyword trends
- No rank tracking
- Keyword difficulty is estimated by Claude, not measured

## When to Upgrade

Upgrade to a real ASO provider when:
- You're shipping more than 2-3 apps per month
- You need accurate keyword volume data to prioritize ideas
- You want to track your app's keyword rankings over time
- You're doing competitive keyword gap analysis

## Supported Providers

### Astro (recommended)

Astro is purpose-built for indie developers shipping multiple apps quickly.

```bash
# In .env
ASO_PROVIDER=astro
ASTRO_API_KEY=your_key_here
```

**What to implement in `agents/keyword_agent.py`:**

```python
def _astro_research(self, refined_idea: RefinedIdea) -> KeywordResearchResult:
    import requests
    
    headers = {"Authorization": f"Bearer {settings.ASTRO_API_KEY}"}
    
    # Get keyword data
    resp = requests.post(
        "https://api.astro.app/v1/keywords/research",
        headers=headers,
        json={
            "seed": refined_idea.name_candidate,
            "country": "us",
            "device": "iphone",
        },
    )
    resp.raise_for_status()
    data = resp.json()
    
    # Map Astro's response to our KeywordOpportunity model
    opportunities = []
    for kw in data["keywords"]:
        opp = KeywordOpportunity(
            term=kw["keyword"],
            popularity_score=kw["volume"],        # 0-100
            competition_score=kw["difficulty"],    # 0-100
            app_count=kw["app_count"],
            opportunity_score=0.0,  # computed by model validator
            source="astro",
        )
        opportunities.append(opp)
    
    primary = max(opportunities, key=lambda k: k.opportunity_score)
    supporting = sorted(
        [k for k in opportunities if k != primary],
        key=lambda k: k.opportunity_score,
        reverse=True,
    )[:settings.KEYWORD_TARGET_COUNT]
    
    keyword_string = self._build_keyword_string(primary, supporting, refined_idea.name_candidate)
    
    return KeywordResearchResult(
        seed_keyword=refined_idea.name_candidate.lower(),
        primary_keyword=primary,
        supporting_keywords=supporting,
        keyword_string=keyword_string,
        rationale=f"Astro data: {primary.term} has volume={primary.popularity_score}, difficulty={primary.competition_score}",
    )
```

### AppFollow

```bash
ASO_PROVIDER=appfollow
APPFOLLOW_API_KEY=your_key_here
```

AppFollow's keyword API docs: https://docs.appfollow.io/keywords

### AppTweak

```bash
ASO_PROVIDER=apptweak
APPTWEAK_API_KEY=your_key_here
```

AppTweak API docs: https://api.apptweak.com/

---

## Upgrade Path for ASOResearchAgent

The `ASOResearchAgent` can also use real ASO data for deeper competitor analysis.

To upgrade competitor scraping:

```python
# In agents/aso_research_agent.py

def _astro_competitors(
    self, keyword: str, refined_idea: RefinedIdea
) -> list[CompetitorApp]:
    """Fetch competitor apps from Astro."""
    import requests
    
    headers = {"Authorization": f"Bearer {settings.ASTRO_API_KEY}"}
    
    resp = requests.get(
        "https://api.astro.app/v1/keywords/top-apps",
        headers=headers,
        params={"keyword": keyword, "country": "us", "limit": 10},
    )
    resp.raise_for_status()
    data = resp.json()
    
    competitors = []
    for app in data["apps"]:
        competitor = CompetitorApp(
            app_id=app["app_id"],
            name=app["title"],
            developer=app["developer"],
            rating=app["rating"],
            rating_count=app["rating_count"],
            price=app["price"],
            has_iap=app["has_iap"],
            description=app.get("description", ""),
            subtitle=app.get("subtitle"),
            screenshot_urls=app.get("screenshots", []),
            icon_url=app.get("icon"),
            category=app.get("category"),
            paywall_style_guess=app.get("business_model"),
        )
        competitors.append(competitor)
    
    return competitors
```

Then in `run()`, check the provider and route accordingly:

```python
if settings.ASO_PROVIDER == "astro":
    competitors = self._astro_competitors(keyword, refined_idea)
else:
    competitors = self._fetch_details(self._search_apps(keyword))
```

---

## Cost Comparison

| Provider | Free Tier | Paid |
|----------|-----------|------|
| Scraper (current) | Free | Free |
| Astro | Limited | ~$29-99/mo |
| AppFollow | Limited | ~$69+/mo |
| AppTweak | No | ~$99+/mo |
| SensorTower | No | Enterprise |

For shipping 1-5 apps/month, the scraper approach is usually sufficient. Upgrade when you're doing volume.
