# iOS Ship Agent 🚀

A fully automated multi-agent pipeline that takes an app idea from zero to **App Store submission-ready package** in minutes.

Inspired by the workflow of Max, a solo indie developer who ships 40+ iOS apps generating $36K/month.

---

## What it does

```
App Idea (string)
       │
       ▼
┌─────────────────┐
│  IdeaAgent      │  Validates & refines the concept
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  KeywordAgent   │  Scrapes App Store search suggestions,
│                 │  ranks keyword opportunities by
│                 │  volume proxy & competition
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  ASOResearch    │  Scrapes top competitor apps:
│  Agent          │  metadata, ratings, descriptions,
│                 │  screenshots, paywall patterns
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  AppBuilder     │  Drives Claude Code CLI to scaffold
│  Agent          │  a full SwiftUI iOS app with
│                 │  onboarding, paywall, core feature
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  VisualAgent    │  Generates app icon via DALL-E 3,
│                 │  composes App Store screenshots
│                 │  (6.7" iPhone 16 Pro Max sizes)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  MetadataAgent  │  Writes App Store metadata:
│                 │  name, subtitle, keyword string,
│                 │  description (keyword-stuffed naturally)
└────────┬────────┘
         │
         ▼
┌─────────────────────────────┐
│  Submission-Ready Package   │
│                             │
│  output/<app_name>/         │
│  ├── xcode_project/         │  Full SwiftUI Xcode project
│  ├── assets/                │
│  │   ├── AppIcon.png        │  1024x1024 icon
│  │   ├── screenshots/       │  6.7" screenshots (x5)
│  │   └── icon_variants/     │  All required icon sizes
│  ├── metadata/              │
│  │   ├── app_store.json     │  Name, subtitle, description
│  │   ├── keywords.txt       │  100-char keyword string
│  │   └── aso_research.json  │  Full competitor analysis
│  └── SUBMISSION_CHECKLIST.md
└─────────────────────────────┘
```

---

## Quick Start

### Prerequisites

```bash
# Python 3.11+
pip install -r requirements.txt

# Claude Code CLI
npm install -g @anthropic-ai/claude-code

# Environment variables
cp .env.example .env
# Fill in: ANTHROPIC_API_KEY, OPENAI_API_KEY
```

### Run

```bash
# Basic
python main.py --idea "An app that identifies plants from photos"

# With options
python main.py \
  --idea "A stamp collector app that identifies and values postage stamps" \
  --output-dir ./output \
  --skip-build   # Skip Claude Code (for testing metadata/visuals only)
  --verbose

# Dry run (no API calls, uses cached fixtures)
python main.py --idea "Plant identifier" --dry-run
```

### Output

Everything lands in `output/<slugified-app-name>/`:

```
output/plant-identifier/
├── xcode_project/          ← Open in Xcode, build & archive
├── assets/
│   ├── AppIcon.png         ← 1024x1024, App Store ready
│   ├── screenshots/        ← 5x iPhone 16 Pro Max screenshots
│   └── icon_variants/      ← All 20 required iOS icon sizes
├── metadata/
│   ├── app_store.json      ← Copy-paste into App Store Connect
│   ├── keywords.txt        ← 100-char keyword string
│   └── aso_research.json   ← Full competitive analysis
└── SUBMISSION_CHECKLIST.md ← Step-by-step final submission guide
```

---

## Architecture

| Agent | Responsibility | External APIs |
|-------|---------------|---------------|
| `IdeaAgent` | Validate & refine app concept | Anthropic Claude |
| `KeywordAgent` | Discover keyword opportunities | App Store (scraped) |
| `ASOResearchAgent` | Competitor analysis | iTunes Search API, App Store (scraped) |
| `AppBuilderAgent` | Scaffold iOS Xcode project | Claude Code CLI |
| `VisualAgent` | Icon + screenshot generation | DALL-E 3, Pillow |
| `MetadataAgent` | App Store metadata copy | Anthropic Claude |
| `OrchestratorAgent` | Pipeline coordination | — |

---

## Configuration

All config lives in `core/config.py`. Key settings:

```python
# ASO keyword scoring weights
KEYWORD_POPULARITY_WEIGHT = 0.6
KEYWORD_COMPETITION_WEIGHT = 0.4
KEYWORD_MIN_SCORE = 0.3

# Screenshot sizes (iPhone 16 Pro Max)
SCREENSHOT_WIDTH = 1320
SCREENSHOT_HEIGHT = 2868

# App Store metadata limits
APP_NAME_MAX = 30
SUBTITLE_MAX = 30
KEYWORDS_MAX = 100
DESCRIPTION_MAX = 4000

# Paywall strategy
DEFAULT_PAYWALL_TIERS = ["weekly", "yearly"]
```

---

## Upgrading to Real ASO Data

When you're ready to swap in Astro (or AppFollow/AppTweak/SensorTower):

1. Set `ASO_PROVIDER=astro` in `.env`
2. Set `ASTRO_API_KEY=your_key` in `.env`
3. The `KeywordAgent` and `ASOResearchAgent` will automatically route to the real API

The scraper implementations remain as fallback.

---

## Upgrading to Auto-Submit

App Store Connect API submission is implemented but gated:

```python
# In .env:
AUTO_SUBMIT=true
APP_STORE_CONNECT_KEY_ID=your_key_id
APP_STORE_CONNECT_ISSUER_ID=your_issuer_id
APP_STORE_CONNECT_KEY_PATH=/path/to/AuthKey.p8
```

Or pass `--submit` flag to `main.py`.

---

## Testing

```bash
# All tests
pytest tests/ -v

# Unit only (no API calls)
pytest tests/unit/ -v

# Integration (requires API keys)
pytest tests/integration/ -v --run-integration

# With coverage
pytest tests/ --cov=agents --cov=core --cov-report=html
```

---

## Project Structure

```
ios_ship_agent/
├── main.py                     ← Entry point
├── requirements.txt
├── .env.example
├── agents/
│   ├── __init__.py
│   ├── base_agent.py           ← Abstract base with retry/logging
│   ├── idea_agent.py
│   ├── keyword_agent.py
│   ├── aso_research_agent.py
│   ├── app_builder_agent.py
│   ├── visual_agent.py
│   ├── metadata_agent.py
│   └── orchestrator.py
├── core/
│   ├── __init__.py
│   ├── config.py               ← All configuration
│   ├── models.py               ← Pydantic data models
│   ├── logger.py               ← Structured logging
│   ├── retry.py                ← Exponential backoff decorator
│   └── app_store_connect.py    ← App Store Connect API (gated)
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── unit/
│   │   ├── test_idea_agent.py
│   │   ├── test_keyword_agent.py
│   │   ├── test_aso_research_agent.py
│   │   ├── test_visual_agent.py
│   │   ├── test_metadata_agent.py
│   │   └── test_models.py
│   ├── integration/
│   │   └── test_full_pipeline.py
│   └── fixtures/
│       ├── keyword_response.json
│       └── competitor_response.json
├── scripts/
│   └── setup.sh                ← One-command environment setup
└── docs/
    ├── ARCHITECTURE.md
    └── ASO_UPGRADE_GUIDE.md
```
