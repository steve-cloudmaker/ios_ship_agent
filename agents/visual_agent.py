"""
VisualAgent

Generates all visual assets for the App Store submission:

1. App icon (1024x1024) via DALL-E 3 (hd quality)
   → Resized to all 15 required iOS icon sizes
   → Saved as AppIcon.appiconset/Contents.json for direct Xcode drop-in

2. App Store screenshots (5x, iPhone 16 Pro Max = 1320x2868)
   → Each screenshot = gradient background + device mockup + headline text
   → Composed with Pillow (no Figma needed)
   → Headlines come from ASOResearchAgent.screenshot_themes

3. Accent color extraction
   → Dominant color from the generated icon
   → Used to coordinate screenshots and metadata

The DALL-E icon is the most AI-involved step. Screenshots are
Pillow-composed from the icon + text, keeping them clean and App Store-safe.
"""

from __future__ import annotations

import io
import json
import math
import re
import textwrap
from pathlib import Path

import openai
import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ios_ship_agent.agents.base_agent import BaseAgent
from ios_ship_agent.core.config import settings
from ios_ship_agent.core.models import (
    ASOResearchResult,
    IconAsset,
    RefinedIdea,
    Screenshot,
    VisualResult,
)
from ios_ship_agent.core.retry import retry


# ---------------------------------------------------------------------------
# DALL-E icon prompt builder
# ---------------------------------------------------------------------------

_ICON_PROMPT_TEMPLATE = """
App Store icon for an iOS app called "{app_name}".

App concept: {core_feature}
Style: Modern, minimal, flat design with subtle depth. App Store quality.
Colors: Use {accent_color} as the primary accent color. 
Background: Solid rounded-square background (the iOS icon shape will be applied by the OS).
Main element: {icon_concept}

Requirements:
- Single focal icon element, centered
- No text, no letters, no words
- High contrast, works at small sizes
- Professional, clean, would look at home next to built-in iOS apps
- No gradients that look dated; use modern material-style depth if any
"""

_ICON_CONCEPT_PROMPT = """
For the iOS app "{app_name}" with core feature "{core_feature}",
suggest the perfect icon concept. The icon should be a single graphic element
that is immediately recognizable, works at small sizes, and communicates
what the app does at a glance.

Respond with a single sentence describing the icon concept.
Examples:
- "A magnifying glass overlaid on a postage stamp"
- "A stylized leaf with a subtle scan line through it"
- "A minimalist camera lens with plant fronds visible through it"

App name: {app_name}
Core feature: {core_feature}
Category: {category}
"""


class VisualAgent(BaseAgent):
    """Generates icon, screenshots, and color palette using DALL-E and Pillow."""

    name = "VisualAgent"

    # Font sizes for screenshots
    HEADLINE_SIZE = 72
    SUBHEADLINE_SIZE = 42
    PADDING = 80

    def __init__(self) -> None:
        super().__init__()
        self._openai = openai.OpenAI(api_key=settings.OPENAI_API_KEY)

    def run(
        self,
        refined_idea: RefinedIdea,
        aso_result: ASOResearchResult,
        output_dir: Path,
    ) -> VisualResult:
        """
        Args:
            refined_idea: Output from IdeaAgent
            aso_result: Output from ASOResearchAgent
            output_dir: Root output directory for this run

        Returns:
            VisualResult with all generated asset paths
        """
        assets_dir = output_dir / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        screenshots_dir = assets_dir / "screenshots"
        screenshots_dir.mkdir(exist_ok=True)
        icon_dir = assets_dir / "icon_variants"
        icon_dir.mkdir(exist_ok=True)

        # Step 1: Get accent color from Claude
        accent_color = self._generate_accent_color(refined_idea)
        self.logger.info(f"Accent color: {accent_color}")

        # Step 2: Generate icon concept
        icon_concept = self._generate_icon_concept(refined_idea)
        self.logger.info(f"Icon concept: {icon_concept}")

        # Step 3: Generate icon via DALL-E
        if settings.DRY_RUN:
            icon_path = self._create_placeholder_icon(assets_dir, accent_color)
        else:
            icon_path = self._generate_icon_dalle(
                refined_idea=refined_idea,
                icon_concept=icon_concept,
                accent_color=accent_color,
                out_dir=assets_dir,
            )

        # Step 4: Generate all icon size variants
        variant_paths = self._generate_icon_variants(icon_path, icon_dir)
        self._write_appiconset(icon_path, icon_dir)
        self.logger.info(f"Generated {len(variant_paths)} icon variants")

        # Step 5: Extract color palette from icon
        palette = self._extract_palette(icon_path, accent_color)

        # Step 6: Generate screenshots
        themes = aso_result.screenshot_themes
        if len(themes) < settings.SCREENSHOT_COUNT:
            themes = (themes + [
                f"Discover the power of {refined_idea.name_candidate}",
                "Your AI assistant for identification",
                "Beautiful results, instantly",
                "Build your collection",
                "Knowledge at your fingertips",
            ])[:settings.SCREENSHOT_COUNT]

        screenshots: list[Screenshot] = []
        for i, theme in enumerate(themes[: settings.SCREENSHOT_COUNT]):
            ss_path = self._compose_screenshot(
                index=i,
                headline=theme,
                icon_path=icon_path,
                accent_color=accent_color,
                palette=palette,
                out_dir=screenshots_dir,
            )
            screenshots.append(
                Screenshot(
                    path=ss_path,
                    width=settings.SCREENSHOT_WIDTH,
                    height=settings.SCREENSHOT_HEIGHT,
                    headline=theme,
                    subheadline="",
                    device_frame=True,
                    sequence=i + 1,
                )
            )
            self.logger.info(f"Screenshot {i+1}/{settings.SCREENSHOT_COUNT}: {theme[:40]}")

        icon_asset = IconAsset(
            source_path=icon_path,
            variant_paths=variant_paths,
            dalle_prompt=_ICON_PROMPT_TEMPLATE.format(
                app_name=refined_idea.name_candidate,
                core_feature=refined_idea.core_feature,
                accent_color=accent_color,
                icon_concept=icon_concept,
            ),
            accent_color_hex=accent_color,
        )

        return VisualResult(
            icon=icon_asset,
            screenshots=screenshots,
            accent_color_hex=accent_color,
            color_palette=palette,
        )

    # ------------------------------------------------------------------
    # Color helpers
    # ------------------------------------------------------------------

    def _generate_accent_color(self, refined_idea: RefinedIdea) -> str:
        """Ask Claude for a good accent color for this app type."""
        raw = self._ask_claude(
            prompt=f"""
For an iOS app called "{refined_idea.name_candidate}" in the {refined_idea.category} category,
what is the best accent color? The app does: {refined_idea.core_feature}

Return ONLY a hex color code like #4F46E5 — nothing else.
Consider: what color feels right for this type of app? Trust, nature, technology?
""",
        )
        # Extract hex
        match = re.search(r"#[0-9A-Fa-f]{6}", raw)
        return match.group(0) if match else "#4F46E5"

    def _extract_palette(self, icon_path: Path, accent: str) -> list[str]:
        """Extract dominant colors from the generated icon."""
        try:
            img = Image.open(icon_path).convert("RGB").resize((50, 50))
            pixels = list(img.getdata())

            # Simple k-means-lite: quantize
            img_small = img.quantize(colors=5)
            palette_raw = img_small.getpalette() or []

            colors: list[str] = []
            for i in range(0, min(len(palette_raw), 15), 3):
                r, g, b = palette_raw[i], palette_raw[i + 1], palette_raw[i + 2]
                hex_color = f"#{r:02X}{g:02X}{b:02X}"
                colors.append(hex_color)

            return [accent] + [c for c in colors if c != accent][:4]
        except Exception:
            return [accent, "#FFFFFF", "#F3F4F6", "#1F2937", "#6B7280"]

    def _hex_to_rgb(self, hex_color: str) -> tuple[int, int, int]:
        hex_color = hex_color.lstrip("#")
        return (
            int(hex_color[0:2], 16),
            int(hex_color[2:4], 16),
            int(hex_color[4:6], 16),
        )

    def _darken(self, hex_color: str, factor: float = 0.7) -> str:
        r, g, b = self._hex_to_rgb(hex_color)
        return f"#{int(r*factor):02X}{int(g*factor):02X}{int(b*factor):02X}"

    def _lighten(self, hex_color: str, factor: float = 0.3) -> str:
        r, g, b = self._hex_to_rgb(hex_color)
        r2 = int(r + (255 - r) * factor)
        g2 = int(g + (255 - g) * factor)
        b2 = int(b + (255 - b) * factor)
        return f"#{r2:02X}{g2:02X}{b2:02X}"

    def _is_dark(self, hex_color: str) -> bool:
        r, g, b = self._hex_to_rgb(hex_color)
        luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255
        return luminance < 0.5

    # ------------------------------------------------------------------
    # Icon generation
    # ------------------------------------------------------------------

    def _generate_icon_concept(self, refined_idea: RefinedIdea) -> str:
        """Ask Claude for the icon concept before sending to DALL-E."""
        return self._ask_claude(
            prompt=_ICON_CONCEPT_PROMPT.format(
                app_name=refined_idea.name_candidate,
                core_feature=refined_idea.core_feature,
                category=refined_idea.category,
            )
        ).strip()

    @retry(max_attempts=3, base_delay=5.0, exceptions=(openai.APIError, openai.RateLimitError))
    def _generate_icon_dalle(
        self,
        refined_idea: RefinedIdea,
        icon_concept: str,
        accent_color: str,
        out_dir: Path,
    ) -> Path:
        """Generate the app icon using DALL-E 3."""
        prompt = _ICON_PROMPT_TEMPLATE.format(
            app_name=refined_idea.name_candidate,
            core_feature=refined_idea.core_feature,
            accent_color=accent_color,
            icon_concept=icon_concept,
        )

        self.logger.info("Requesting icon from DALL-E 3...")
        response = self._openai.images.generate(
            model=settings.DALLE_MODEL,
            prompt=prompt,
            size=settings.DALLE_ICON_SIZE,  # type: ignore[arg-type]
            quality=settings.DALLE_ICON_QUALITY,  # type: ignore[arg-type]
            n=1,
        )

        image_url = response.data[0].url
        if not image_url:
            raise ValueError("DALL-E returned no image URL")

        img_data = requests.get(image_url, timeout=60).content
        icon_path = out_dir / "AppIcon.png"
        icon_path.write_bytes(img_data)

        # Validate
        img = Image.open(icon_path)
        if img.size != (1024, 1024):
            img = img.resize((1024, 1024), Image.LANCZOS)
            img.save(icon_path)

        self.logger.info(f"Icon saved: {icon_path}")
        return icon_path

    def _create_placeholder_icon(self, out_dir: Path, accent_color: str) -> Path:
        """Create a simple placeholder icon in dry-run mode."""
        img = Image.new("RGBA", (1024, 1024), self._hex_to_rgb(accent_color))
        draw = ImageDraw.Draw(img)
        # Draw a simple geometric shape
        margin = 200
        draw.ellipse(
            [margin, margin, 1024 - margin, 1024 - margin],
            fill=(255, 255, 255, 180),
        )
        icon_path = out_dir / "AppIcon.png"
        img.save(icon_path)
        return icon_path

    def _generate_icon_variants(
        self, source: Path, out_dir: Path
    ) -> dict[str, Path]:
        """Resize the master 1024x1024 icon to all required iOS sizes."""
        img = Image.open(source).convert("RGBA")
        variants: dict[str, Path] = {}

        for size_name, pixel_size in settings.ICON_SIZES.items():
            resized = img.resize((pixel_size, pixel_size), Image.LANCZOS)
            safe_name = size_name.replace(".", "_").replace("@", "_at_")
            out_path = out_dir / f"AppIcon_{safe_name}.png"
            resized.save(out_path, "PNG")
            variants[size_name] = out_path

        return variants

    def _write_appiconset(self, source: Path, out_dir: Path) -> None:
        """
        Write an AppIcon.appiconset/ folder with Contents.json
        for direct drop-in to an Xcode project.
        """
        appiconset = out_dir / "AppIcon.appiconset"
        appiconset.mkdir(exist_ok=True)

        # Copy 1024 master
        import shutil
        shutil.copy(source, appiconset / "AppIcon-1024.png")

        images = []
        for size_name, pixel_size in settings.ICON_SIZES.items():
            # Parse "60x60@2x" -> size=60, scale=2x
            match = re.match(r"([\d.]+)x[\d.]+@(\d+)x", size_name)
            if not match:
                continue
            pt_size = match.group(1)
            scale = match.group(2) + "x"

            safe_name = size_name.replace(".", "_").replace("@", "_at_")
            filename = f"AppIcon_{safe_name}.png"

            # Resize and copy
            img = Image.open(source).convert("RGBA")
            resized = img.resize((pixel_size, pixel_size), Image.LANCZOS)
            resized.save(appiconset / filename)

            images.append({
                "filename": filename,
                "idiom": "iphone" if float(pt_size) <= 60 else "ipad",
                "scale": scale,
                "size": f"{pt_size}x{pt_size}",
            })

        # 1024 for App Store
        images.append({
            "filename": "AppIcon-1024.png",
            "idiom": "ios-marketing",
            "scale": "1x",
            "size": "1024x1024",
        })

        contents = {"images": images, "info": {"author": "xcode", "version": 1}}
        (appiconset / "Contents.json").write_text(json.dumps(contents, indent=2))

    # ------------------------------------------------------------------
    # Screenshot composition
    # ------------------------------------------------------------------

    def _compose_screenshot(
        self,
        index: int,
        headline: str,
        icon_path: Path,
        accent_color: str,
        palette: list[str],
        out_dir: Path,
    ) -> Path:
        """
        Compose a professional App Store screenshot using Pillow.

        Layout:
        - Full gradient background (accent -> darker shade)
        - Large headline text (centered, top third)
        - App icon (center, circular masked)
        - Subtle decorative elements
        """
        W, H = settings.SCREENSHOT_WIDTH, settings.SCREENSHOT_HEIGHT
        img = Image.new("RGBA", (W, H))

        # Background gradient
        dark = self._darken(accent_color, 0.55)
        light = self._lighten(accent_color, 0.15)
        img = self._draw_gradient(img, light, dark)

        draw = ImageDraw.Draw(img)

        # Try to load a font; fall back to default
        font_large = self._load_font(self.HEADLINE_SIZE)
        font_small = self._load_font(self.SUBHEADLINE_SIZE)

        # Headline text (wrapped, centered, upper area)
        text_color = "white"
        wrapped = textwrap.fill(headline, width=22)
        text_y = int(H * 0.08)
        draw.multiline_text(
            (W // 2, text_y),
            wrapped,
            font=font_large,
            fill=text_color,
            anchor="ma",
            align="center",
            spacing=16,
        )

        # App icon (centered, lower half)
        icon_img = Image.open(icon_path).convert("RGBA")
        icon_size = int(W * 0.55)
        icon_img = icon_img.resize((icon_size, icon_size), Image.LANCZOS)

        # Rounded corners on icon
        icon_img = self._round_corners(icon_img, radius=int(icon_size * 0.22))

        # Shadow
        shadow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        shadow_img = Image.new("RGBA", (icon_size + 20, icon_size + 20), (0, 0, 0, 80))
        shadow_layer.paste(shadow_img, (W // 2 - icon_size // 2 - 10 + 15, int(H * 0.38) + 10))
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(25))
        img = Image.alpha_composite(img, shadow_layer)

        icon_x = W // 2 - icon_size // 2
        icon_y = int(H * 0.38)
        img.paste(icon_img, (icon_x, icon_y), icon_img)

        # Decorative dot grid (subtle)
        draw = ImageDraw.Draw(img)
        self._draw_dot_grid(draw, W, H, accent_color)

        # Index indicator dots at bottom
        self._draw_page_dots(draw, W, H, index, settings.SCREENSHOT_COUNT, accent_color)

        out_path = out_dir / f"screenshot_{index + 1:02d}.png"
        img.convert("RGB").save(out_path, "PNG", quality=95)
        return out_path

    def _draw_gradient(self, img: Image.Image, top_hex: str, bottom_hex: str) -> Image.Image:
        """Draw a vertical gradient on the image."""
        W, H = img.size
        top = self._hex_to_rgb(top_hex)
        bottom = self._hex_to_rgb(bottom_hex)

        gradient = Image.new("RGBA", (W, H))
        draw = ImageDraw.Draw(gradient)
        for y in range(H):
            ratio = y / H
            r = int(top[0] + (bottom[0] - top[0]) * ratio)
            g = int(top[1] + (bottom[1] - top[1]) * ratio)
            b = int(top[2] + (bottom[2] - top[2]) * ratio)
            draw.line([(0, y), (W, y)], fill=(r, g, b, 255))

        return Image.alpha_composite(img, gradient)

    def _draw_dot_grid(self, draw: ImageDraw.Draw, W: int, H: int, accent: str) -> None:
        """Draw a subtle dot grid pattern."""
        r, g, b = self._hex_to_rgb(accent)
        color = (min(r + 60, 255), min(g + 60, 255), min(b + 60, 255), 30)
        spacing = 40
        radius = 2
        for x in range(0, W, spacing):
            for y in range(0, H, spacing):
                draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=color)

    def _draw_page_dots(
        self,
        draw: ImageDraw.Draw,
        W: int,
        H: int,
        current: int,
        total: int,
        accent: str,
    ) -> None:
        """Draw page indicator dots at the bottom."""
        dot_r = 8
        gap = 24
        total_w = total * (dot_r * 2) + (total - 1) * gap
        start_x = (W - total_w) // 2
        y = H - 80

        for i in range(total):
            x = start_x + i * (dot_r * 2 + gap)
            if i == current:
                draw.ellipse([x, y - dot_r, x + dot_r * 2, y + dot_r], fill="white")
            else:
                draw.ellipse(
                    [x, y - dot_r, x + dot_r * 2, y + dot_r],
                    fill=(255, 255, 255, 80),
                )

    def _round_corners(self, img: Image.Image, radius: int) -> Image.Image:
        """Apply rounded corners to an RGBA image."""
        mask = Image.new("L", img.size, 0)
        draw = ImageDraw.Draw(mask)
        draw.rounded_rectangle([0, 0, img.width, img.height], radius=radius, fill=255)
        result = img.copy()
        result.putalpha(mask)
        return result

    def _load_font(self, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        """Try to load a system font, fall back to default."""
        font_paths = [
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/SFNSDisplay.ttf",
            "/System/Library/Fonts/Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ]
        for fp in font_paths:
            try:
                return ImageFont.truetype(fp, size)
            except (OSError, IOError):
                continue

        return ImageFont.load_default()
