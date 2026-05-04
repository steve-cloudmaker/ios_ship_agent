# Architecture — iOS Ship Agent

## Overview

The pipeline is a sequential multi-agent system. Each agent has a single responsibility, well-defined typed inputs/outputs (via Pydantic), and is independently testable.

```
User Input (app idea string)
        │
        ▼
┌───────────────────────────────────────────────────────────────┐
│  OrchestratorAgent                                            │
│                                                               │
│  ┌─────────────┐   ┌──────────────┐   ┌────────────────────┐ │
│  │ IdeaAgent   │──▶│ KeywordAgent │──▶│ ASOResearchAgent   │ │
│  └─────────────┘   └──────────────┘   └────────────────────┘ │
│         │                │                       │            │
│         └────────────────┴───────────────────────┘            │
│                                    │                          │
│                          ┌─────────▼─────────┐               │
│                          │  AppBuilderAgent  │               │
│                          └─────────┬─────────┘               │
│                                    │                          │
│                          ┌─────────▼─────────┐               │
│                          │   VisualAgent     │               │
│                          └─────────┬─────────┘               │
│                                    │                          │
│                          ┌─────────▼─────────┐               │
│                          │  MetadataAgent    │               │
│                          └─────────┬─────────┘               │
│                                    │                          │
│                        Package Assembly                       │
└───────────────────────────────────────────────────────────────┘
        │
        ▼
output/<slug>/   (submission-ready package)
```

---

## Agent Details

### IdeaAgent

**Purpose:** Validate and structure the raw user input.

**Inputs:** `AppIdea` (raw string)

**Outputs:** `RefinedIdea` (structured concept)

**How it works:**
1. Sends the raw idea to Claude with a structured JSON prompt
2. Claude returns: name candidate, slug, core feature, target user, value prop, category, AI capability, paywall strategy, viability score
3. Agent validates with Pydantic, warns if viability < 0.5

**Key decision:** Paywall strategy is decided here. Single-use apps (like "remove background from one photo once") get `lifetime` pricing; recurring-use apps get `weekly + yearly`.

---

### KeywordAgent

**Purpose:** Discover the best App Store keywords to target.

**Inputs:** `RefinedIdea`

**Outputs:** `KeywordResearchResult` (primary keyword + keyword string)

**How it works:**
1. **Autocomplete scraping:** Hits the App Store search hint API with the seed term to get real autocomplete suggestions (the same ones users see when typing in the App Store)
2. **iTunes keyword extraction:** Searches iTunes Search API for competing apps, pulls keyword signals from app names and descriptions
3. **Claude scoring:** Sends all candidates to Claude for popularity/competition scoring
4. **Opportunity ranking:** `opportunity_score = (popularity × 0.6) - (competition × 0.4)`
5. **Keyword string:** Claude builds the 100-char keyword field, avoiding repeats from the name/subtitle

**Public APIs used (no auth needed):**
- `https://search.itunes.apple.com/WebObjects/MZSearchHints.woa/wa/hints` — autocomplete
- `https://itunes.apple.com/search` — app search
- `https://itunes.apple.com/lookup` — app detail

**Future:** Replace scraper with Astro/AppFollow for real volume + difficulty data. Set `ASO_PROVIDER=astro` in `.env`.

---

### ASOResearchAgent

**Purpose:** Understand the competitive landscape.

**Inputs:** `RefinedIdea`, `KeywordResearchResult`

**Outputs:** `ASOResearchResult` (competitor intel, market gaps)

**How it works:**
1. Searches iTunes Search API for the primary keyword
2. Parses top 8 competitors: name, rating, rating count, price, IAP, description, paywall style
3. Sends to Claude for analysis: common value props, screenshot themes, paywall patterns, market gaps
4. Falls back to Claude synthesis if no results found

**Non-fatal:** The orchestrator continues even if this agent fails (uses empty ASO data).

---

### AppBuilderAgent

**Purpose:** Build a complete SwiftUI iOS Xcode project.

**Inputs:** `RefinedIdea`, `KeywordResearchResult`, `ASOResearchResult`, `output_dir`

**Outputs:** `AppBuildResult` (project path, build status)

**How it works:**
Uses the Claude Code CLI (`claude --continue -p "prompt"`) in 6 sequential steps:

1. **Scaffold** — App entry point, TabView, stub screens, Assets.xcassets with accent color
2. **Core feature** — Camera viewfinder, photo library picker, AI identification API call, results card
3. **Onboarding** — 3-screen full-page onboarding with progress dots, `@AppStorage` state
4. **Paywall** — StoreKit 2 integration, subscription options, gradient design
5. **History + Collection + Settings** — Core Data persistence, grid/list views, settings screen
6. **Final check** — Import fixes, TabView wiring, StoreManager injection, `#Preview` macros

**`--continue` flag:** Each prompt continues the previous Claude Code session, so Claude has full context of all previously created files when writing each subsequent component.

**Build verification:** Runs `xcodebuild` after all prompts complete to verify compilation. Build failure is non-fatal — the project is still included in the package.

---

### VisualAgent

**Purpose:** Generate all App Store visual assets.

**Inputs:** `RefinedIdea`, `ASOResearchResult`, `output_dir`

**Outputs:** `VisualResult` (icon, screenshots, palette)

**How it works:**

1. **Accent color:** Claude picks a hex color appropriate for the app category
2. **Icon concept:** Claude writes a 1-sentence description of the ideal icon
3. **DALL-E 3 icon:** Sends a structured prompt to DALL-E 3 (hd quality, 1024x1024)
4. **Icon variants:** Pillow resizes the master to all 15 required iOS sizes
5. **AppIcon.appiconset:** Writes the full `Contents.json` for Xcode drop-in
6. **Color palette:** Extracts dominant colors from the generated icon via PIL quantization
7. **Screenshots (x5):** Pillow-composed at 1320×2868 (iPhone 16 Pro Max):
   - Gradient background (accent → darker shade)
   - App icon (centered, rounded corners, shadow)
   - Headline text (from ASOResearchAgent screenshot themes)
   - Subtle dot grid pattern
   - Page indicator dots

No Figma, no external templates — everything composited by Pillow.

---

### MetadataAgent

**Purpose:** Write all App Store Connect copy.

**Inputs:** `RefinedIdea`, `KeywordResearchResult`, `ASOResearchResult`, `VisualResult`

**Outputs:** `AppStoreMetadata` (validated against all App Store limits)

**Character limits enforced (double-validated by Pydantic + agent):**
- App Name: 30 chars
- Subtitle: 30 chars
- Keywords: 100 chars
- Description: 4000 chars
- Promotional Text: 170 chars

**Also generates:**
- 3 onboarding screen titles
- 4 paywall benefit titles
- 5 screenshot headlines

---

### OrchestratorAgent

**Purpose:** Run the full pipeline and assemble the submission package.

**Error handling:**
- `ASOResearchAgent` failure → non-fatal, defaults used
- `AppBuilderAgent` failure → non-fatal, project included as-is
- `IdeaAgent`, `KeywordAgent`, `VisualAgent`, `MetadataAgent` failures → fatal (no package)

**Output package assembly:**
```
output/<slug>/
├── xcode_project/
├── assets/
│   ├── AppIcon.png
│   ├── screenshots/
│   └── icon_variants/AppIcon.appiconset/
├── metadata/
│   ├── app_store.json
│   ├── keywords.txt
│   ├── keyword_research.json
│   └── aso_research.json
├── pipeline_result.json
└── SUBMISSION_CHECKLIST.md
```

---

## Data Flow (Pydantic Models)

```
AppIdea
  → RefinedIdea (IdeaAgent)
  → KeywordResearchResult (KeywordAgent)
  → ASOResearchResult (ASOResearchAgent)
  → AppBuildResult (AppBuilderAgent)
  → VisualResult (VisualAgent)
  → AppStoreMetadata (MetadataAgent)
  → PipelineResult (Orchestrator)
```

All models live in `core/models.py`. No agent passes raw dicts between stages.

---

## Retry Strategy

All API calls use the `@retry` decorator from `core/retry.py`:
- 3 attempts
- 2s base delay, 2x backoff (so: 2s, 4s, 8s)
- Catches `anthropic.APIError`, `anthropic.RateLimitError`, `requests.RequestException`

---

## Configuration

All config is in `core/config.py` via `pydantic-settings`. Environment variables (or `.env`) override any default. CLI flags in `main.py` set `os.environ` before the settings object is created.

Priority: CLI flags > .env > defaults
