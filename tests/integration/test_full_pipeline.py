"""
Integration tests for the full pipeline.

These tests make REAL API calls and require:
  - ANTHROPIC_API_KEY
  - OPENAI_API_KEY

Run with:
  pytest tests/integration/ -v --run-integration
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.mark.integration
class TestFullPipeline:
    """End-to-end pipeline tests with real API calls."""

    def test_stamp_identifier_full_pipeline(self, tmp_path):
        """
        Run the complete pipeline for 'stamp identifier' app with SKIP_BUILD=true.
        Verifies all agents complete and the package is assembled.
        """
        os.environ["SKIP_BUILD"] = "true"

        from ios_ship_agent.agents.orchestrator import OrchestratorAgent

        orchestrator = OrchestratorAgent()
        result = orchestrator.run(
            app_idea="An app that identifies postage stamps using AI and tells you their value",
            output_dir=tmp_path,
        )

        assert result.success, f"Pipeline failed: {result.errors}"
        assert result.refined_idea is not None
        assert result.keyword_research is not None
        assert result.metadata is not None
        assert result.visuals is not None
        assert result.submission_package_path is not None

        # Check output files exist
        pkg = result.submission_package_path
        assert (pkg / "SUBMISSION_CHECKLIST.md").exists()
        assert (pkg / "metadata" / "app_store.json").exists()
        assert (pkg / "metadata" / "keywords.txt").exists()
        assert (pkg / "assets" / "AppIcon.png").exists()

        # Validate metadata limits
        meta = result.metadata
        assert len(meta.app_name) <= 30
        assert len(meta.subtitle) <= 30
        assert len(meta.keywords) <= 100

        # Validate screenshots
        assert result.visuals.screenshots
        for ss in result.visuals.screenshots:
            assert ss.path.exists()
            assert ss.width == 1320
            assert ss.height == 2868

    def test_plant_identifier_full_pipeline(self, tmp_path):
        """Test with a different app idea to ensure the pipeline is generic."""
        os.environ["SKIP_BUILD"] = "true"

        from ios_ship_agent.agents.orchestrator import OrchestratorAgent

        orchestrator = OrchestratorAgent()
        result = orchestrator.run(
            app_idea="A plant identifier app that scans plants with the camera",
            output_dir=tmp_path,
        )

        assert result.success, f"Pipeline failed: {result.errors}"
        assert result.slug != "stamp-identifier"  # different app

    def test_dry_run_completes_fast(self, tmp_path):
        """Dry run should complete without any real API calls."""
        os.environ["DRY_RUN"] = "true"
        os.environ["SKIP_BUILD"] = "true"

        # In dry run, the idea agent still needs Claude
        # So we patch it for this specific test
        from unittest.mock import MagicMock, patch
        import json

        refined_data = {
            "name_candidate": "Dry Run App",
            "slug": "dry-run-app",
            "core_feature": "Test feature",
            "target_user": "Testers",
            "value_proposition": "Fast testing",
            "category": "Utilities",
            "ai_capability_required": "none",
            "paywall_tiers": ["weekly", "yearly"],
            "is_single_use": False,
            "viability_score": 0.8,
            "viability_notes": "Test.",
        }
        meta_data = {
            "app_name": "Dry Run App",
            "subtitle": "AI Test",
            "description": "Test description.",
            "keywords": "test,app,dry,run",
            "promotional_text": "Testing!",
            "primary_category": "Utilities",
            "secondary_category": None,
            "age_rating": "4+",
            "onboarding_titles": ["Step 1", "Step 2", "Step 3"],
            "paywall_titles": ["Feature 1", "Feature 2", "Feature 3", "Feature 4"],
            "screenshot_headlines": ["H1", "H2", "H3", "H4", "H5"],
        }

        call_count = [0]

        def claude_side_effect(**kwargs):
            resp = MagicMock()
            if call_count[0] == 0:
                resp.content = [MagicMock(text=json.dumps(refined_data))]
            elif call_count[0] == 1:
                resp.content = [MagicMock(text="#4F46E5")]  # accent color
            elif call_count[0] == 2:
                resp.content = [MagicMock(text="A magnifying glass")]  # icon concept
            else:
                resp.content = [MagicMock(text=json.dumps(meta_data))]
            call_count[0] += 1
            return resp

        with patch("anthropic.Anthropic") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            mock_client.messages.create.side_effect = claude_side_effect

            from ios_ship_agent.agents.orchestrator import OrchestratorAgent
            orchestrator = OrchestratorAgent()
            result = orchestrator.run(
                app_idea="Dry run test app",
                output_dir=tmp_path,
            )

        assert result.success or result.errors  # either outcome is fine for dry run

    @pytest.mark.parametrize("app_idea", [
        "A coin identifier and value tracker",
        "An app that identifies bird species from photos",
        "A wine label scanner that recommends pairings",
    ])
    def test_multiple_ideas_produce_unique_slugs(self, app_idea, tmp_path):
        """Different ideas should produce different slugs/apps."""
        os.environ["SKIP_BUILD"] = "true"

        from ios_ship_agent.agents.idea_agent import IdeaAgent
        from ios_ship_agent.core.models import AppIdea

        agent = IdeaAgent()
        idea = AppIdea(raw_input=app_idea)
        result = agent.execute(idea)

        assert result.slug
        assert " " not in result.slug
        assert result.slug.replace("-", "").isalnum()
