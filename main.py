#!/usr/bin/env python3
"""
iOS Ship Agent — Main Entry Point

Usage:
    python main.py --idea "A plant identification app using AI"
    python main.py --idea "Stamp identifier" --skip-build --verbose
    python main.py --idea "Coin collector" --dry-run
    python main.py --idea "Recipe scanner" --output-dir ~/Desktop/my_apps
    python main.py --idea "Mood tracker" --submit  # requires AUTO_SUBMIT config
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ios-ship-agent",
        description="Automated iOS app pipeline: idea → App Store submission package",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--idea",
        type=str,
        required=True,
        help="Your app idea (e.g. 'An AI plant identifier app')",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Output directory (default: ./output/<app-slug>/)",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        default=False,
        help="Skip Claude Code build step (generates visuals + metadata only)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="No real API calls — uses fixture/placeholder data (for testing)",
    )
    parser.add_argument(
        "--submit",
        action="store_true",
        default=False,
        help="Submit to App Store Connect after packaging (requires AUTO_SUBMIT config)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=False,
        help="Verbose logging (DEBUG level)",
    )
    parser.add_argument(
        "--aso-provider",
        type=str,
        choices=["scraper", "astro", "appfollow", "apptweak"],
        default=None,
        help="Override ASO_PROVIDER from .env",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # Apply CLI overrides to settings before importing agents
    if args.skip_build:
        os.environ["SKIP_BUILD"] = "true"
    if args.dry_run:
        os.environ["DRY_RUN"] = "true"
    if args.verbose:
        os.environ["LOG_LEVEL"] = "DEBUG"
    if args.submit:
        os.environ["AUTO_SUBMIT"] = "true"
    if args.aso_provider:
        os.environ["ASO_PROVIDER"] = args.aso_provider

    # Validate required env vars before going further
    missing = []
    if not os.environ.get("ANTHROPIC_API_KEY") and not args.dry_run:
        missing.append("ANTHROPIC_API_KEY")
    if not os.environ.get("OPENAI_API_KEY") and not args.dry_run:
        missing.append("OPENAI_API_KEY")

    if missing:
        print(f"ERROR: Missing required environment variables: {', '.join(missing)}")
        print("Copy .env.example to .env and fill in your API keys.")
        return 1

    # Import after env vars are set (pydantic-settings reads env at import time)
    from ios_ship_agent.agents.orchestrator import OrchestratorAgent

    orchestrator = OrchestratorAgent()

    try:
        result = orchestrator.run(
            app_idea=args.idea,
            output_dir=args.output_dir,
        )
        return 0 if result.success else 1
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        return 130
    except Exception as exc:
        print(f"Fatal error: {exc}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
