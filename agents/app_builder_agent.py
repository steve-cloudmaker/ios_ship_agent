"""
AppBuilderAgent

Drives the Claude Code CLI (`claude`) to scaffold a complete SwiftUI iOS app.

Strategy:
1. Generate a boilerplate from the template (creates Xcode project structure)
2. Send focused, iterative prompts to Claude Code for each major component:
   - Core feature screen (camera + AI identification)
   - Onboarding flow (3 screens)
   - Paywall screen
   - Tab navigation
   - Settings screen
   - History/collection screens
3. Run three smaller “final review” Claude Code prompts (imports/nav, state/services, previews);
   timeouts on those steps log a warning and still run `xcodebuild`.

4. Run `xcodebuild` to verify the project compiles

Claude Code CLI reference:
  claude -p "prompt" --output-format json
  claude --continue  (continues previous session)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

from ios_ship_agent.agents.base_agent import BaseAgent
from ios_ship_agent.core.config import settings
from ios_ship_agent.core.models import (
    AppBuildResult,
    AppBuildSpec,
    ASOResearchResult,
    KeywordResearchResult,
    PaywallTier,
    RefinedIdea,
    SwiftFeature,
)


# ---------------------------------------------------------------------------
# Claude Code prompts
# ---------------------------------------------------------------------------

_PROMPT_SCAFFOLD = """
Create a new SwiftUI iOS app named "{app_name}" with bundle ID "{bundle_id}".

Requirements:
- SwiftUI, iOS {deployment_target}+
- Tab-based navigation with these tabs:
{tabs}

Create all the Swift files needed for a working Xcode project:
- App entry point (App.swift)
- ContentView.swift with TabView
- One stub view per tab
- Basic Assets.xcassets with accent color {accent_color}
- Info.plist with NSCameraUsageDescription and NSPhotoLibraryUsageDescription

Make sure it compiles cleanly. Use modern Swift concurrency (async/await).
"""

_PROMPT_CORE_FEATURE = """
Implement the main feature screen for {app_name}: {core_feature}

AI capability: {ai_capability}

The screen should:
1. Show a camera viewfinder (using AVFoundation's camera preview)
2. Have a "Photo Library" button to pick from gallery  
3. Have a large primary action button: "Identify" / "Scan"
4. On tap, call the analyzeImage() function (async)
5. Show a loading state while analyzing
6. Display results in a card below: title, value estimate, historical facts
7. Show a "Request Review" prompt (SKStoreReviewController) only on successful results

The analyzeImage() function should:
- Accept a UIImage
- Convert to base64
- Call the AI API (Claude or Gemini — use a placeholder APIService)
- Return a structured result: name, value, description, historical_context

Create:
- {feature_name}View.swift (the main feature view)
- APIService.swift (async AI identification service with protocol + mock)
- IdentificationResult.swift (Codable model)
"""

_PROMPT_ONBOARDING = """
Create a beautiful onboarding flow for {app_name}.

Screens (3 total):
{onboarding_titles}

Requirements:
- Full-screen illustrated onboarding
- Progress dots at the bottom
- "Continue" button on each screen
- "Skip" button in top right (except last screen)
- Last screen has "Get Started" button
- After completion, show the paywall

Create:
- OnboardingView.swift (container with page transitions)
- OnboardingPageView.swift (single page component)
- Use @AppStorage("hasSeenOnboarding") to persist state
- Use SF Symbols for illustrations (large, centered)
"""

_PROMPT_PAYWALL = """
Create a paywall screen for {app_name}.

Paywall configuration:
- Weekly subscription: $2.99/week with {trial_days}-day free trial
- Yearly subscription: $19.99/year
- Title: "Go {app_name} Pro"
- 4 feature bullets:
{paywall_bullets}

Requirements:
- Full-screen modal presentation
- Gradient background using accent color
- App icon + "PRO" badge at top
- Feature list with checkmarks
- Two subscription buttons (Weekly highlighted, Yearly below)
- "Restore Purchases" link at bottom
- "Terms of Use" and "Privacy Policy" links
- StoreKit 2 integration (use @EnvironmentObject for StoreManager)

Create:
- PaywallView.swift
- StoreManager.swift (StoreKit 2 with product fetching + purchase handling)
"""

_PROMPT_HISTORY_COLLECTION = """
Create the History and Collection screens for {app_name}.

History Screen:
- List of all past identifications (most recent first)
- Each row: thumbnail, name, date, estimated value
- Swipe to delete
- Tap to view full details

Collection Screen:
- Grid view of all saved items
- Total collection value shown in header
- "Add to Collection" toggle on each identification result
- Sort by: date, value, name

Create:
- HistoryView.swift
- CollectionView.swift
- ScanHistoryItem.swift (Core Data entity model)
- PersistenceController.swift (Core Data stack)
"""

_PROMPT_SETTINGS = """
Create a Settings screen for {app_name}.

Sections:
1. Subscription — "Manage Subscription" (opens App Store), "Restore Purchases"
2. App — "Rate {app_name}" (SKStoreReviewController), "Share App"
3. Legal — "Privacy Policy", "Terms of Use"
4. Support — "Contact Us" (mailto link)

Requirements:
- Standard grouped list style
- Show subscription status (Free / Pro) at top
- Tapping "Manage Subscription" opens app subscription management URL

Create: SettingsView.swift
"""

_PROMPT_FINAL_IMPORTS_NAV = """
For SwiftUI project {app_name}, fix imports and tab navigation only:

1. Ensure every Swift file imports the frameworks it uses (SwiftUI, AVFoundation, StoreKit, etc.).
2. Ensure TabView lists every tab and each tab shows the intended screen view.
3. Fix any incorrect or missing imports that block compilation.

Output a brief list of files you changed.
"""

_PROMPT_FINAL_STATE_SERVICES = """
For SwiftUI project {app_name}, fix state and services wiring:

1. Fix missing @EnvironmentObject or @StateObject declarations throughout the app.
2. Ensure onboarding correctly gates access to the main app (paywall/onboarding flow).
3. Verify StoreManager is created once and injected at the app root (@main).
4. Confirm APIService has a concrete implementation plus MockAPIService for previews/tests.

Output a brief summary of changes only.
"""

_PROMPT_FINAL_PREVIEWS = """
For SwiftUI project {app_name}:

1. Add #Preview (or Xcode-supported preview pattern) to every View file missing one.
2. Output a one-line summary of view files touched.

Keep edits minimal aside from previews unless required to compile previews.
"""


class AppBuilderAgent(BaseAgent):
    """Drives Claude Code CLI to scaffold and build the iOS app."""

    name = "AppBuilderAgent"

    def run(
        self,
        refined_idea: RefinedIdea,
        keyword_result: KeywordResearchResult,
        aso_result: ASOResearchResult,
        output_dir: Path,
    ) -> AppBuildResult:
        """
        Args:
            refined_idea: Output from IdeaAgent
            keyword_result: Output from KeywordAgent
            aso_result: Output from ASOResearchAgent
            output_dir: Root output directory for this run

        Returns:
            AppBuildResult with project path and build status
        """
        if settings.SKIP_BUILD or settings.DRY_RUN:
            self.logger.info("Skipping app build (SKIP_BUILD or DRY_RUN is set)")
            return self._stub_result(refined_idea, output_dir)

        # Check Claude Code is available
        self._check_claude_code()

        spec = self._build_spec(refined_idea, keyword_result, aso_result)
        project_dir = output_dir / "xcode_project"
        project_dir.mkdir(parents=True, exist_ok=True)

        self.logger.info(f"Building '{spec.app_name}' at {project_dir}")

        prompts_run: list[str] = []
        build_log_parts: list[str] = []

        # Step 1: Scaffold
        p1 = self._make_scaffold_prompt(spec)
        scaffold_output = self._run_claude_code(p1, project_dir)
        if not any(project_dir.iterdir()):
            snippet = (scaffold_output or "").strip().splitlines()[:40]
            raise RuntimeError(
                "Claude Code scaffold step produced no files in xcode_project/. "
                "This typically means Claude Code ran without edit permissions. "
                "Recent output:\n"
                + "\n".join(snippet)
            )
        prompts_run.append(p1)
        build_log_parts.append("✓ Scaffold complete")
        self.logger.info("✓ Step 1/8: Scaffold done")

        # Step 2: Core feature
        p2 = self._make_core_feature_prompt(spec, aso_result)
        self._run_claude_code(p2, project_dir, continue_session=True)
        prompts_run.append(p2)
        build_log_parts.append("✓ Core feature complete")
        self.logger.info("✓ Step 2/8: Core feature done")

        # Step 3: Onboarding
        p3 = self._make_onboarding_prompt(spec, aso_result)
        self._run_claude_code(p3, project_dir, continue_session=True)
        prompts_run.append(p3)
        build_log_parts.append("✓ Onboarding complete")
        self.logger.info("✓ Step 3/8: Onboarding done")

        # Step 4: Paywall
        p4 = self._make_paywall_prompt(spec, aso_result)
        self._run_claude_code(p4, project_dir, continue_session=True)
        prompts_run.append(p4)
        build_log_parts.append("✓ Paywall complete")
        self.logger.info("✓ Step 4/8: Paywall done")

        # Step 5: History + Collection + Settings
        p5 = _PROMPT_HISTORY_COLLECTION.format(app_name=spec.app_name)
        self._run_claude_code(p5, project_dir, continue_session=True)
        p6 = _PROMPT_SETTINGS.format(app_name=spec.app_name)
        self._run_claude_code(p6, project_dir, continue_session=True)
        prompts_run.extend([p5, p6])
        build_log_parts.append("✓ History/Collection/Settings complete")
        self.logger.info("✓ Step 5/8: History/Collection/Settings done")

        # Steps 6–8: Split final review (smaller Claude Code calls); timeouts continue to xcodebuild
        final_prompts = [
            (
                "imports/navigation",
                _PROMPT_FINAL_IMPORTS_NAV.format(app_name=spec.app_name),
                "✓ Final review — imports/navigation complete",
                "⚠ Final review — imports/navigation timed out (continuing)",
            ),
            (
                "state/services",
                _PROMPT_FINAL_STATE_SERVICES.format(app_name=spec.app_name),
                "✓ Final review — state & services complete",
                "⚠ Final review — state & services timed out (continuing)",
            ),
            (
                "previews",
                _PROMPT_FINAL_PREVIEWS.format(app_name=spec.app_name),
                "✓ Final review — previews complete",
                "⚠ Final review — previews timed out (continuing)",
            ),
        ]
        final_check_had_timeout = False
        for step_idx, (short_label, prompt, ok_msg, timeout_msg) in enumerate(
            final_prompts, start=6
        ):
            prompts_run.append(prompt)
            finished = self._run_claude_code_continue_on_timeout(
                prompt,
                project_dir,
                step_label=f"final review ({short_label})",
            )
            if finished:
                build_log_parts.append(ok_msg)
                self.logger.info(f"✓ Step {step_idx}/8: Final review pass done")
            else:
                final_check_had_timeout = True
                build_log_parts.append(timeout_msg)

        # Try xcodebuild
        build_succeeded, xcode_log = self._try_xcodebuild(project_dir, spec)
        build_log_parts.append(xcode_log)

        warnings: list[str] = []
        if final_check_had_timeout:
            warnings.append(
                "One or more final-review Claude Code steps timed out — verify the Xcode project manually."
            )
        if not build_succeeded:
            warnings.append("xcodebuild verification failed — check logs")

        return AppBuildResult(
            project_path=project_dir,
            bundle_id=spec.bundle_id,
            scheme_name=spec.app_name,
            build_succeeded=build_succeeded,
            build_log="\n".join(build_log_parts),
            claude_code_prompts=prompts_run,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # Prompt builders
    # ------------------------------------------------------------------

    def _build_spec(
        self,
        refined_idea: RefinedIdea,
        keyword_result: KeywordResearchResult,
        aso_result: ASOResearchResult,
    ) -> AppBuildSpec:
        app_name = refined_idea.name_candidate.replace(" ", "")  # strip spaces for Xcode

        # Generate a stable bundle ID from the slug
        slug_clean = re.sub(r"[^a-z0-9]", "", refined_idea.slug)
        bundle_id = f"com.indie.{slug_clean}"

        screens = [
            SwiftFeature(name="MainFeature", description=refined_idea.core_feature, tab_icon="camera"),
            SwiftFeature(name="History", description="Scan history", tab_icon="clock"),
            SwiftFeature(name="Collection", description="Saved collection", tab_icon="folder"),
            SwiftFeature(name="Settings", description="App settings", tab_icon="gear"),
        ]

        return AppBuildSpec(
            app_name=app_name,
            bundle_id=bundle_id,
            core_feature=refined_idea.core_feature,
            ai_capability=refined_idea.ai_capability_required,
            screens=screens,
            paywall_tiers=refined_idea.paywall_strategy,
        )

    def _make_scaffold_prompt(self, spec: AppBuildSpec) -> str:
        tabs = "\n".join(
            f"  - {s.name} (SF Symbol: {s.tab_icon})" for s in spec.screens
        )
        return _PROMPT_SCAFFOLD.format(
            app_name=spec.app_name,
            bundle_id=spec.bundle_id,
            deployment_target=spec.deployment_target,
            tabs=tabs,
            accent_color=spec.accent_color_hex,
        )

    def _make_core_feature_prompt(self, spec: AppBuildSpec, aso: ASOResearchResult) -> str:
        return _PROMPT_CORE_FEATURE.format(
            app_name=spec.app_name,
            core_feature=spec.core_feature,
            ai_capability=spec.ai_capability,
            feature_name=spec.screens[0].name,
        )

    def _make_onboarding_prompt(self, spec: AppBuildSpec, aso: ASOResearchResult) -> str:
        titles = aso.screenshot_themes[:3] if aso.screenshot_themes else [
            "Point your camera at any item",
            "Get instant AI-powered results",
            "Build your collection",
        ]
        formatted = "\n".join(f"  {i+1}. {t}" for i, t in enumerate(titles))
        return _PROMPT_ONBOARDING.format(
            app_name=spec.app_name,
            onboarding_titles=formatted,
        )

    def _make_paywall_prompt(self, spec: AppBuildSpec, aso: ASOResearchResult) -> str:
        bullets = aso.paywall_patterns[:4] if aso.paywall_patterns else [
            "Unlimited Scans",
            "Full History Access",
            "AI-Powered Analysis",
            "Ad-Free Experience",
        ]
        formatted = "\n".join(f"  • {b}" for b in bullets)
        return _PROMPT_PAYWALL.format(
            app_name=spec.app_name,
            trial_days=settings.FREE_TRIAL_DAYS,
            paywall_bullets=formatted,
        )

    # ------------------------------------------------------------------
    # Claude Code runner
    # ------------------------------------------------------------------

    def _check_claude_code(self) -> None:
        """Verify claude CLI is installed."""
        result = subprocess.run(
            ["which", "claude"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise EnvironmentError(
                "Claude Code CLI not found. Install with: npm install -g @anthropic-ai/claude-code\n"
                "Or set SKIP_BUILD=true in .env to skip the build step."
            )
        self.logger.info(f"Claude Code CLI found: {result.stdout.strip()}")

    def _run_claude_code(
        self,
        prompt: str,
        cwd: Path,
        continue_session: bool = False,
    ) -> str:
        """
        Run a Claude Code CLI command and return the output.

        Args:
            prompt: The prompt to send
            cwd: Working directory (the Xcode project dir)
            continue_session: Whether to continue the previous session

        Returns:
            Claude Code's output text
        """
        cmd = [
            "claude",
            "--output-format",
            "text",
            "--permission-mode",
            "acceptEdits",
        ]
        if continue_session:
            cmd.append("--continue")
        cmd += ["-p", prompt]

        env = os.environ.copy()
        env["ANTHROPIC_API_KEY"] = settings.ANTHROPIC_API_KEY

        self.logger.debug(f"Running Claude Code (continue={continue_session})")

        try:
            result = subprocess.run(
                cmd,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=settings.CLAUDE_CODE_TIMEOUT_SECONDS,
                env=env,
                stdin=subprocess.DEVNULL,
            )
            output = result.stdout + result.stderr
            if result.returncode != 0:
                self.logger.warning(f"Claude Code exited {result.returncode}: {result.stderr[:500]}")
            return output
        except subprocess.TimeoutExpired:
            self.logger.error(f"Claude Code timed out after {settings.CLAUDE_CODE_TIMEOUT_SECONDS}s")
            raise

    def _run_claude_code_continue_on_timeout(
        self,
        prompt: str,
        cwd: Path,
        step_label: str,
    ) -> bool:
        """
        Run Claude Code; on timeout log a warning and return False so the caller
        can still run xcodebuild (does not abort AppBuilderAgent).
        """
        try:
            self._run_claude_code(prompt, cwd, continue_session=True)
            return True
        except subprocess.TimeoutExpired:
            self.logger.warning(
                "Claude Code timed out (%s) after %ss — continuing pipeline (xcodebuild next).",
                step_label,
                settings.CLAUDE_CODE_TIMEOUT_SECONDS,
            )
            return False

    def _try_xcodebuild(self, project_dir: Path, spec: AppBuildSpec) -> tuple[bool, str]:
        """
        Attempt to compile the project with xcodebuild.
        Returns (success, log).
        """
        # Find the .xcodeproj
        xcodeprojs = list(project_dir.glob("**/*.xcodeproj"))
        if not xcodeprojs:
            self.logger.warning("No .xcodeproj found — skipping xcodebuild verification")
            return False, "No .xcodeproj found"

        xcodeproj = xcodeprojs[0]
        self.logger.info(f"Running xcodebuild on {xcodeproj.name}")

        cmd = [
            "xcodebuild",
            "-project", str(xcodeproj),
            "-scheme", spec.app_name,
            "-destination", "platform=iOS Simulator,name=iPhone 16 Pro",
            "-quiet",
            "build",
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
                cwd=str(project_dir),
            )
            if result.returncode == 0:
                self.logger.info("✓ xcodebuild succeeded")
                return True, "✓ xcodebuild build succeeded"
            else:
                self.logger.warning(f"xcodebuild failed (exit {result.returncode})")
                return False, f"xcodebuild failed:\n{result.stderr[-2000:]}"
        except FileNotFoundError:
            self.logger.warning("xcodebuild not found — are you on macOS with Xcode installed?")
            return False, "xcodebuild not available"
        except subprocess.TimeoutExpired:
            return False, "xcodebuild timed out"

    # ------------------------------------------------------------------
    # Stub / dry-run
    # ------------------------------------------------------------------

    def _stub_result(self, refined_idea: RefinedIdea, output_dir: Path) -> AppBuildResult:
        """Return a stub result when build is skipped."""
        project_dir = output_dir / "xcode_project"
        project_dir.mkdir(parents=True, exist_ok=True)

        # Write a README explaining the project would be here
        (project_dir / "README.md").write_text(
            f"# {refined_idea.name_candidate}\n\n"
            "This directory would contain the Xcode project generated by Claude Code.\n"
            "Run without --skip-build or DRY_RUN=false to generate the actual project.\n"
        )

        slug_clean = re.sub(r"[^a-z0-9]", "", refined_idea.slug)
        return AppBuildResult(
            project_path=project_dir,
            bundle_id=f"com.indie.{slug_clean}",
            scheme_name=refined_idea.name_candidate.replace(" ", ""),
            build_succeeded=False,
            build_log="Build skipped (SKIP_BUILD=true or DRY_RUN=true)",
            claude_code_prompts=[],
            warnings=["Build was skipped"],
        )
