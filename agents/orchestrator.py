"""
OrchestratorAgent

Coordinates all agents in sequence, handles errors gracefully,
and writes the final submission-ready package.

Pipeline order:
  IdeaAgent → KeywordAgent → ASOResearchAgent →
  AppBuilderAgent → VisualAgent → MetadataAgent →
  Package Assembly

Also writes:
- SUBMISSION_CHECKLIST.md (step-by-step App Store submission guide)
- metadata/app_store.json (copy-paste ready)
- metadata/aso_research.json (full competitive intel)
- pipeline_result.json (full run record for debugging)
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from ios_ship_agent.agents.app_builder_agent import AppBuilderAgent
from ios_ship_agent.agents.aso_research_agent import ASOResearchAgent
from ios_ship_agent.agents.idea_agent import IdeaAgent
from ios_ship_agent.agents.keyword_agent import KeywordAgent
from ios_ship_agent.agents.metadata_agent import MetadataAgent
from ios_ship_agent.agents.visual_agent import VisualAgent
from ios_ship_agent.core.config import settings
from ios_ship_agent.core.logger import console, get_logger, log_pipeline_banner
from ios_ship_agent.core.models import AppIdea, AgentStatus, PipelineResult

logger = get_logger("ios_ship_agent.orchestrator", level=settings.LOG_LEVEL)


class OrchestratorAgent:
    """Runs the full pipeline and assembles the submission package."""

    def run(self, app_idea: str, output_dir: Path | None = None) -> PipelineResult:
        """
        Execute the full pipeline for the given app idea.

        Args:
            app_idea: The user's raw app idea string
            output_dir: Override output directory (default: settings.OUTPUT_DIR)

        Returns:
            PipelineResult with all outputs and pipeline metadata
        """
        run_id = str(uuid.uuid4())[:8]
        started_at = datetime.utcnow()

        log_pipeline_banner(logger, app_idea)
        logger.info(f"Run ID: {run_id}")

        # Initialize agents
        idea_agent = IdeaAgent()
        keyword_agent = KeywordAgent()
        aso_agent = ASOResearchAgent()
        builder_agent = AppBuilderAgent()
        visual_agent = VisualAgent()
        metadata_agent = MetadataAgent()

        idea = AppIdea(raw_input=app_idea)

        result = PipelineResult(
            run_id=run_id,
            app_idea=app_idea,
            slug="unknown",
            output_dir=Path("."),
            started_at=started_at,
        )

        # ----------------------------------------------------------------
        # Stage 1: Idea refinement
        # ----------------------------------------------------------------
        try:
            refined = idea_agent.execute(idea)
            result.refined_idea = refined
            result.slug = refined.slug
            result.agent_runs.append(idea_agent.run_record)
        except Exception as exc:
            result.agent_runs.append(idea_agent.run_record)
            return self._fail(result, f"IdeaAgent failed: {exc}")

        # Set up output directory
        run_output_dir = (output_dir or settings.OUTPUT_DIR) / refined.slug
        run_output_dir.mkdir(parents=True, exist_ok=True)
        result.output_dir = run_output_dir
        logger.info(f"Output directory: {run_output_dir}")

        # ----------------------------------------------------------------
        # Stage 2: Keyword research
        # ----------------------------------------------------------------
        try:
            keyword_result = keyword_agent.execute(refined)
            result.keyword_research = keyword_result
            result.agent_runs.append(keyword_agent.run_record)
        except Exception as exc:
            result.agent_runs.append(keyword_agent.run_record)
            return self._fail(result, f"KeywordAgent failed: {exc}")

        # ----------------------------------------------------------------
        # Stage 3: ASO competitor research
        # ----------------------------------------------------------------
        try:
            aso_result = aso_agent.execute(refined, keyword_result)
            result.aso_research = aso_result
            result.agent_runs.append(aso_agent.run_record)
        except Exception as exc:
            result.agent_runs.append(aso_agent.run_record)
            logger.warning(f"ASOResearchAgent failed: {exc} — continuing with defaults")
            # Non-fatal: create empty ASO result
            from ios_ship_agent.core.models import ASOResearchResult
            aso_result = ASOResearchResult(
                keyword=keyword_result.primary_keyword.term,
                screenshot_themes=[
                    f"Discover {refined.name_candidate}",
                    "Instant AI identification",
                    "Build your collection",
                    "Your history, organized",
                    "Trusted by enthusiasts",
                ],
                paywall_patterns=["Unlimited Scans", "Full History", "AI Analysis", "Ad-Free"],
                common_value_props=[],
                market_gaps=[],
            )
            result.aso_research = aso_result

        # ----------------------------------------------------------------
        # Stage 4: App build (Claude Code)
        # ----------------------------------------------------------------
        try:
            build_result = builder_agent.execute(refined, keyword_result, aso_result, run_output_dir)
            result.app_build = build_result
            result.agent_runs.append(builder_agent.run_record)
            if not build_result.build_succeeded:
                logger.warning("App build did not fully compile — check xcode_project/")
        except Exception as exc:
            result.agent_runs.append(builder_agent.run_record)
            logger.warning(f"AppBuilderAgent failed: {exc} — continuing with visuals/metadata")

        # ----------------------------------------------------------------
        # Stage 5: Visual generation
        # ----------------------------------------------------------------
        try:
            visual_result = visual_agent.execute(refined, aso_result, run_output_dir)
            result.visuals = visual_result
            result.agent_runs.append(visual_agent.run_record)
        except Exception as exc:
            result.agent_runs.append(visual_agent.run_record)
            return self._fail(result, f"VisualAgent failed: {exc}")

        # ----------------------------------------------------------------
        # Stage 6: Metadata generation
        # ----------------------------------------------------------------
        try:
            metadata = metadata_agent.execute(refined, keyword_result, aso_result, visual_result)
            result.metadata = metadata
            result.agent_runs.append(metadata_agent.run_record)
        except Exception as exc:
            result.agent_runs.append(metadata_agent.run_record)
            return self._fail(result, f"MetadataAgent failed: {exc}")

        # ----------------------------------------------------------------
        # Stage 7: Package assembly
        # ----------------------------------------------------------------
        self._assemble_package(result, run_output_dir)

        # ----------------------------------------------------------------
        # Finalize
        # ----------------------------------------------------------------
        finished_at = datetime.utcnow()
        result.finished_at = finished_at
        result.total_duration_seconds = (finished_at - started_at).total_seconds()
        result.success = True
        result.submission_package_path = run_output_dir

        self._write_pipeline_result(result, run_output_dir)
        self._print_summary(result)

        return result

    # ------------------------------------------------------------------
    # Package assembly
    # ------------------------------------------------------------------

    def _assemble_package(self, result: PipelineResult, output_dir: Path) -> None:
        """Write all metadata files and submission checklist."""
        metadata_dir = output_dir / "metadata"
        metadata_dir.mkdir(exist_ok=True)

        # app_store.json — copy-paste ready for App Store Connect
        if result.metadata:
            app_store_data = result.metadata.model_dump()
            (metadata_dir / "app_store.json").write_text(
                json.dumps(app_store_data, indent=2, default=str)
            )

            # keywords.txt — separate file for convenience
            (metadata_dir / "keywords.txt").write_text(result.metadata.keywords)

        # aso_research.json
        if result.aso_research:
            aso_data = result.aso_research.model_dump()
            (metadata_dir / "aso_research.json").write_text(
                json.dumps(aso_data, indent=2, default=str)
            )

        # keyword_research.json
        if result.keyword_research:
            kw_data = result.keyword_research.model_dump()
            (metadata_dir / "keyword_research.json").write_text(
                json.dumps(kw_data, indent=2, default=str)
            )

        # SUBMISSION_CHECKLIST.md
        checklist = self._build_checklist(result)
        (output_dir / "SUBMISSION_CHECKLIST.md").write_text(checklist)

        logger.info(f"Package assembled at: {output_dir}")

    def _build_checklist(self, result: PipelineResult) -> str:
        """Generate a step-by-step App Store submission checklist."""
        meta = result.metadata
        build = result.app_build
        visuals = result.visuals

        slug = result.slug
        app_name = meta.app_name if meta else slug
        bundle_id = build.bundle_id if build else f"com.indie.{slug}"

        lines = [
            f"# App Store Submission Checklist — {app_name}",
            f"\nGenerated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
            f"Run ID: {result.run_id}",
            "\n---\n",
            "## Before Submitting\n",
            "### 1. Xcode Project",
            f"- [ ] Open `xcode_project/` in Xcode",
            f"- [ ] Set Bundle ID to `{bundle_id}`",
            f"- [ ] Set your Development Team (Signing & Capabilities)",
            f"- [ ] Update deployment target if needed (current: iOS 17.0+)",
            f"- [ ] Add your real API keys to APIService.swift",
            f"- [ ] Run on a real device (camera functionality requires hardware)",
            f"- [ ] Test the full onboarding + paywall flow",
            f"- [ ] Test a real purchase with StoreKit sandbox",
            f"- [ ] Archive (Product → Archive) for submission",
            "",
            "### 2. App Store Connect — New App Setup",
            f"- [ ] Go to https://appstoreconnect.apple.com",
            f"- [ ] Click '+' to add a new app",
            f"- [ ] Bundle ID: `{bundle_id}` (register first at developer.apple.com if needed)",
            f"- [ ] Primary Language: English (U.S.)",
            f"- [ ] SKU: `{bundle_id.replace('.', '-')}`",
            "",
            "### 3. App Information",
        ]

        if meta:
            lines += [
                f"- [ ] Name: `{meta.app_name}` ({len(meta.app_name)}/30 chars)",
                f"- [ ] Subtitle: `{meta.subtitle}` ({len(meta.subtitle)}/30 chars)",
                f"- [ ] Primary Category: {meta.primary_category}",
                f"- [ ] Age Rating: {meta.age_rating}",
                f"- [ ] Privacy Policy URL: (add your URL)",
                f"- [ ] Support URL: (add your URL)",
            ]

        lines += [
            "",
            "### 4. Version Information (1.0)",
        ]

        if meta:
            lines += [
                f"- [ ] Description: Copy from `metadata/app_store.json` → `description`",
                f"- [ ] Keywords: `{meta.keywords}` ({len(meta.keywords)}/100 chars)",
                f"  → File: `metadata/keywords.txt`",
                f"- [ ] Promotional Text: `{meta.promotional_text}`",
            ]

        lines += [
            "",
            "### 5. Screenshots",
            f"- [ ] Upload all 5 screenshots from `assets/screenshots/`",
            f"- [ ] These are sized for iPhone 16 Pro Max (6.7\") — required",
            f"- [ ] Screenshots are in display order (01 = first shown)",
            "",
            "### 6. App Icon",
            f"- [ ] Drag `assets/icon_variants/AppIcon.appiconset/` into your Xcode Assets.xcassets",
            f"- [ ] Verify 1024x1024 icon is set in App Store Connect",
            "",
            "### 7. Pricing",
            f"- [ ] Set Price: Free (monetized via IAP)",
            f"- [ ] Set up In-App Purchases in App Store Connect:",
        ]

        if result.refined_idea:
            for tier in result.refined_idea.paywall_strategy:
                if tier.value == "weekly":
                    lines.append(f"  - [ ] Weekly Auto-Renewable: $2.99/week (3-day free trial)")
                elif tier.value == "yearly":
                    lines.append(f"  - [ ] Yearly Auto-Renewable: $19.99/year")
                elif tier.value == "monthly":
                    lines.append(f"  - [ ] Monthly Auto-Renewable: $4.99/month")
                elif tier.value == "lifetime":
                    lines.append(f"  - [ ] Lifetime Non-Consumable: $9.99")

        lines += [
            "",
            "### 8. Review Information",
            f"- [ ] Demo account (if login required): N/A",
            f"- [ ] Notes for reviewer: 'Camera permission is required for the core scanning feature. "
            f"A simulator cannot test camera; please test on device.'",
            "",
            "### 9. Submit",
            f"- [ ] Upload build via Xcode Organizer (Product → Archive → Distribute App)",
            f"- [ ] Select the uploaded build in App Store Connect",
            f"- [ ] Click 'Submit for Review'",
            f"- [ ] Expected review time: 24-48 hours",
            "",
            "---",
            "",
            "## Auto-Submit (Future)",
            "",
            "To enable automatic submission via the App Store Connect API:",
            "```",
            "AUTO_SUBMIT=true",
            "APP_STORE_CONNECT_KEY_ID=your_key_id",
            "APP_STORE_CONNECT_ISSUER_ID=your_issuer_id",
            "APP_STORE_CONNECT_KEY_PATH=/path/to/AuthKey.p8",
            "```",
            "",
            "Then pass `--submit` to `main.py`.",
            "",
            "---",
            "",
            "## Files in This Package",
            "",
            "```",
            f"output/{slug}/",
            "├── xcode_project/          ← Open in Xcode",
            "├── assets/",
            "│   ├── AppIcon.png         ← 1024x1024 master icon",
            "│   ├── screenshots/        ← 5x iPhone 16 Pro Max screenshots",
            "│   └── icon_variants/",
            "│       └── AppIcon.appiconset/  ← Drop into Xcode Assets",
            "├── metadata/",
            "│   ├── app_store.json      ← All metadata, copy-paste ready",
            "│   ├── keywords.txt        ← 100-char keyword string",
            "│   ├── keyword_research.json",
            "│   └── aso_research.json   ← Competitor analysis",
            "├── pipeline_result.json    ← Full run record",
            "└── SUBMISSION_CHECKLIST.md ← This file",
            "```",
        ]

        if meta:
            lines += [
                "",
                "---",
                "",
                "## Metadata Quick Reference",
                "",
                f"**App Name:** {meta.app_name}",
                f"**Subtitle:** {meta.subtitle}",
                f"**Keywords:** {meta.keywords}",
                "",
                "**Onboarding Titles:**",
            ]
            for title in meta.onboarding_titles:
                lines.append(f"1. {title}")
            lines += [
                "",
                "**Paywall Feature Titles:**",
            ]
            for title in meta.paywall_titles:
                lines.append(f"• {title}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _fail(self, result: PipelineResult, error: str) -> PipelineResult:
        result.success = False
        result.errors.append(error)
        finished_at = datetime.utcnow()
        result.finished_at = finished_at
        result.total_duration_seconds = (finished_at - result.started_at).total_seconds()
        logger.error(f"Pipeline failed: {error}")
        return result

    def _write_pipeline_result(self, result: PipelineResult, output_dir: Path) -> None:
        """Write the full pipeline result as JSON for debugging."""
        data = result.summary()
        (output_dir / "pipeline_result.json").write_text(
            json.dumps(data, indent=2, default=str)
        )

    def _print_summary(self, result: PipelineResult) -> None:
        """Print a rich summary table."""
        console.rule("[bold green]Pipeline Complete[/bold green]")

        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Agent", style="cyan")
        table.add_column("Status")
        table.add_column("Duration")
        table.add_column("Retries")

        status_icons = {
            AgentStatus.SUCCESS: "[green]✓ success[/green]",
            AgentStatus.FAILED: "[red]✗ failed[/red]",
            AgentStatus.SKIPPED: "[yellow]⊘ skipped[/yellow]",
            AgentStatus.PENDING: "[dim]○ pending[/dim]",
            AgentStatus.RUNNING: "[blue]◉ running[/blue]",
        }

        for run in result.agent_runs:
            duration = f"{run.duration_seconds:.1f}s" if run.duration_seconds else "—"
            table.add_row(
                run.agent_name,
                status_icons.get(run.status, run.status),
                duration,
                str(run.retries),
            )

        console.print(table)
        console.print()

        if result.success and result.submission_package_path:
            console.print(
                f"[bold green]✓ Submission package ready:[/bold green] "
                f"{result.submission_package_path}"
            )
        if result.metadata:
            console.print(f"  App Name:  [cyan]{result.metadata.app_name}[/cyan]")
            console.print(f"  Subtitle:  {result.metadata.subtitle}")
            console.print(f"  Keywords:  {result.metadata.keywords}")

        if result.total_duration_seconds:
            console.print(
                f"\n[dim]Total time: {result.total_duration_seconds:.0f}s "
                f"({result.total_duration_seconds/60:.1f}min)[/dim]"
            )

        console.rule()
