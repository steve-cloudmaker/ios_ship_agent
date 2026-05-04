# CLAUDE.md — ios_ship_agent

This file gives Claude Code (and future Claude sessions) full context on this project.

---

## What This Project Does

`ios_ship_agent` is a multi-agent Python pipeline that takes a raw app idea string and produces a **complete, App Store submission-ready package** — including a SwiftUI Xcode project, App Store screenshots, app icon, and all metadata copy.

The pipeline runs locally on macOS and is designed for indie developers who want to ship iOS apps fast.

---

## Architecture

```
main.py  →  OrchestratorAgent
               ├── IdeaAgent          (Claude: refine + validate concept)
               ├── KeywordAgent       (iTunes Search API + Claude: ASO keywords)
               ├── ASOResearchAgent   (iTunes Search API + Claude: competitor intel)
               ├── AppBuilderAgent    (Claude Code CLI: scaffold SwiftUI project)
               ├── VisualAgent        (DALL-E 3 + Pillow: icon + screenshots)
               └── MetadataAgent      (Claude: App Store copy)
```

**Key files:**
- `core/models.py` — All Pydantic data models. Every inter-agent handoff is typed.
- `core/config.py` — pydantic-settings. All config via `.env` or env vars.
- `agents/base_agent.py` — Abstract base. All agents inherit `_ask_claude()`, `_ask_claude_json()`, retry logic.
- `agents/orchestrator.py` — Pipeline coordinator. Writes the submission package.
- `core/app_store_connect.py` — App Store Connect API. **100% gated behind `AUTO_SUBMIT=false`.**

---

## Running the Pipeline

```bash
# Full run
python main.py --idea "An app that identifies postage stamps and tells you their value"

# Skip the Xcode build (just metadata + visuals)
python main.py --idea "Plant identifier" --skip-build

# Dry run (no real API calls)
python main.py --idea "Stamp identifier" --dry-run

# Verbose
python main.py --idea "Coin scanner" --skip-build --verbose
```

**Output lands in:** `output/<app-slug>/`

---

## Testing

```bash
# Fast: unit tests only (no API keys needed)
pytest tests/unit/ -v

# Full: integration tests (requires ANTHROPIC_API_KEY + OPENAI_API_KEY)
pytest tests/integration/ -v --run-integration
```

52 unit tests, 0 external API calls needed.

---

## Environment Variables

```bash
cp .env.example .env
# Required:
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...

# Optional gates:
SKIP_BUILD=false       # Skip Claude Code iOS build
DRY_RUN=false          # Skip all API calls
AUTO_SUBMIT=false      # Gate on App Store Connect submission
ASO_PROVIDER=scraper   # scraper | astro | appfollow | apptweak
```

---

## Key Conventions

- **No raw dicts between agents.** All data is Pydantic models defined in `core/models.py`.
- **Settings are a singleton.** Import `from ios_ship_agent.core.config import settings` everywhere.
- **All agents extend `BaseAgent`.** Use `self._ask_claude()` and `self._ask_claude_json()` for LLM calls — these have retry built in.
- **Call `agent.execute()` from orchestrator**, not `agent.run()` — `execute()` handles timing and status tracking.
- **App Store Connect is always no-op** unless `AUTO_SUBMIT=true`. Never change this default.
- **Character limits are enforced twice:** in Pydantic validators AND in `MetadataAgent._enforce_limit()`. Never skip validation.

---

## Adding a New Agent

1. Create `agents/my_agent.py` extending `BaseAgent`
2. Add input/output Pydantic models to `core/models.py`
3. Add to `PipelineResult` in `core/models.py`
4. Wire into `OrchestratorAgent.run()` in `agents/orchestrator.py`
5. Add unit tests in `tests/unit/test_my_agent.py`

---

## Planned Upgrades

| Feature | How |
|---------|-----|
| Real ASO data | Set `ASO_PROVIDER=astro` + `ASTRO_API_KEY`. See `docs/ASO_UPGRADE_GUIDE.md` |
| Auto App Store submission | Set `AUTO_SUBMIT=true` + App Store Connect key files. All code already exists in `core/app_store_connect.py` |
| Parallel agents | `asyncio.gather()` for KeywordAgent + ASOResearchAgent (they're independent) |
| App idea scoring | Add a pre-pipeline step to score multiple ideas before committing |

---

## Output Package Structure

```
output/<app-slug>/
├── xcode_project/               ← Open in Xcode, archive, distribute
├── assets/
│   ├── AppIcon.png              ← 1024x1024 master
│   ├── screenshots/             ← 5x iPhone 16 Pro Max (1320x2868)
│   └── icon_variants/
│       └── AppIcon.appiconset/  ← Drop into Xcode Assets.xcassets
├── metadata/
│   ├── app_store.json           ← Copy-paste into App Store Connect
│   ├── keywords.txt             ← 100-char keyword string
│   ├── keyword_research.json    ← Full keyword analysis
│   └── aso_research.json        ← Competitor analysis
├── pipeline_result.json         ← Full run record for debugging
└── SUBMISSION_CHECKLIST.md      ← Step-by-step submission guide
```
