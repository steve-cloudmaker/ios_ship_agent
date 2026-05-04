"""Unit tests for VisualAgent."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image


class TestVisualAgent:
    @pytest.fixture(autouse=True)
    def patch_deps(self, tmp_path):
        self.tmp_path = tmp_path
        with patch("anthropic.Anthropic") as mock_anthropic_cls, \
             patch("openai.OpenAI") as mock_openai_cls:
            self.mock_anthropic = MagicMock()
            mock_anthropic_cls.return_value = self.mock_anthropic
            self.mock_openai = MagicMock()
            mock_openai_cls.return_value = self.mock_openai
            yield

    def _set_claude_response(self, text: str) -> None:
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=text)]
        self.mock_anthropic.messages.create.return_value = mock_response

    def _set_dalle_response(self, img_path: Path) -> None:
        """Mock DALL-E to return a real PNG file."""
        img = Image.new("RGB", (1024, 1024), (75, 70, 229))
        img.save(img_path)
        img_bytes = img_path.read_bytes()

        mock_image_resp = MagicMock()
        mock_image_resp.url = f"file://{img_path}"

        mock_resp = MagicMock()
        mock_resp.data = [mock_image_resp]
        self.mock_openai.images.generate.return_value = mock_resp

        # Patch requests.get to return the image bytes
        with patch("requests.get") as mock_get:
            mock_get.return_value = MagicMock(content=img_bytes)
            yield mock_get

    def _make_agent(self):
        from ios_ship_agent.agents.visual_agent import VisualAgent
        return VisualAgent()

    def test_generate_accent_color_returns_hex(self, refined_stamp, aso_result):
        self._set_claude_response("#4F46E5")
        agent = self._make_agent()
        color = agent._generate_accent_color(refined_stamp)
        assert color.startswith("#")
        assert len(color) == 7

    def test_generate_accent_color_fallback_on_no_hex(self, refined_stamp):
        self._set_claude_response("I think indigo would work well for this app.")
        agent = self._make_agent()
        color = agent._generate_accent_color(refined_stamp)
        # Should fall back to default
        assert color == "#4F46E5"

    def test_hex_to_rgb_conversion(self):
        agent = self._make_agent()
        r, g, b = agent._hex_to_rgb("#4B46E5")
        assert r == 75
        assert g == 70
        assert b == 229

    def test_darken_reduces_values(self):
        agent = self._make_agent()
        dark = agent._darken("#FFFFFF", 0.5)
        r, g, b = agent._hex_to_rgb(dark)
        assert r == 127 or r == 128  # rounding
        assert g == 127 or g == 128
        assert b == 127 or b == 128

    def test_lighten_increases_values(self):
        agent = self._make_agent()
        light = agent._lighten("#000000", 0.5)
        r, g, b = agent._hex_to_rgb(light)
        assert r == 127 or r == 128
        assert g == 127 or g == 128
        assert b == 127 or b == 128

    def test_is_dark_on_dark_color(self):
        agent = self._make_agent()
        assert agent._is_dark("#000000") is True
        assert agent._is_dark("#1F2937") is True

    def test_is_dark_on_light_color(self):
        agent = self._make_agent()
        assert agent._is_dark("#FFFFFF") is False
        assert agent._is_dark("#F3F4F6") is False

    def test_placeholder_icon_created(self, refined_stamp, aso_result, tmp_path):
        self._set_claude_response("#4B46E5")
        agent = self._make_agent()
        icon_path = agent._create_placeholder_icon(tmp_path, "#4B46E5")

        assert icon_path.exists()
        img = Image.open(icon_path)
        assert img.size == (1024, 1024)

    def test_generate_icon_variants_creates_all_sizes(self, tmp_path):
        from ios_ship_agent.core.config import settings

        # Create a source icon
        source = tmp_path / "AppIcon.png"
        img = Image.new("RGB", (1024, 1024), (75, 70, 229))
        img.save(source)

        agent = self._make_agent()
        icon_dir = tmp_path / "variants"
        icon_dir.mkdir()
        variants = agent._generate_icon_variants(source, icon_dir)

        assert len(variants) == len(settings.ICON_SIZES)
        for size_name, path in variants.items():
            assert path.exists()
            img = Image.open(path)
            expected_size = settings.ICON_SIZES[size_name]
            assert img.size == (expected_size, expected_size)

    def test_round_corners_returns_rgba(self, tmp_path):
        img = Image.new("RGBA", (100, 100), (255, 0, 0, 255))
        agent = self._make_agent()
        rounded = agent._round_corners(img, radius=10)
        assert rounded.mode == "RGBA"
        # Corner should be transparent
        assert rounded.getpixel((0, 0))[3] == 0  # type: ignore[index]

    def test_compose_screenshot_creates_file(self, tmp_path):
        # Create a mock icon
        icon_path = tmp_path / "AppIcon.png"
        img = Image.new("RGBA", (1024, 1024), (75, 70, 229, 255))
        img.save(icon_path)

        agent = self._make_agent()
        out_dir = tmp_path / "screenshots"
        out_dir.mkdir()

        ss_path = agent._compose_screenshot(
            index=0,
            headline="Point. Scan. Identify.",
            icon_path=icon_path,
            accent_color="#4B46E5",
            palette=["#4B46E5", "#FFFFFF"],
            out_dir=out_dir,
        )

        assert ss_path.exists()
        img = Image.open(ss_path)
        from ios_ship_agent.core.config import settings
        assert img.size == (settings.SCREENSHOT_WIDTH, settings.SCREENSHOT_HEIGHT)

    def test_write_appiconset_creates_contents_json(self, tmp_path):
        source = tmp_path / "AppIcon.png"
        img = Image.new("RGBA", (1024, 1024), (75, 70, 229, 255))
        img.save(source)

        agent = self._make_agent()
        agent._write_appiconset(source, tmp_path)

        appiconset = tmp_path / "AppIcon.appiconset"
        assert appiconset.exists()
        contents = json.loads((appiconset / "Contents.json").read_text())
        assert "images" in contents
        assert len(contents["images"]) > 0

    def test_dry_run_uses_placeholder(self, refined_stamp, aso_result, tmp_path):
        import os
        os.environ["DRY_RUN"] = "true"
        try:
            self._set_claude_response("#4B46E5\nA magnifying glass over a postage stamp")
            agent = self._make_agent()
            icon_path = agent._create_placeholder_icon(tmp_path, "#4B46E5")
            assert icon_path.exists()
        finally:
            os.environ["DRY_RUN"] = "false"
