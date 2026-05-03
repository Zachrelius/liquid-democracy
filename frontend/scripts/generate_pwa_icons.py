"""Phase 10 W4 — Generate placeholder PWA icons.

Creates three PNG icons (192, 512, maskable-512) using a simple text-based
"LD" mark in white sans-serif on the verified brand navy (#1B3A5C). The
maskable variant inscribes the text inside the inner 80% of the canvas so
that browsers' automatic masks (squircle, circle, rounded square) don't
clip the mark.

Run from the repo root:
    backend/.venv/Scripts/python frontend/scripts/generate_pwa_icons.py

A future pass will replace these with a real platform brand mark; per
Phase 10 design decision 13, this is a deliberate placeholder.
"""

from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

BRAND = (27, 58, 92)  # #1B3A5C, verified Tailwind brand navy
WHITE = (255, 255, 255)
TEXT = "LD"
# Icons live in frontend/public/icons/; this script lives in frontend/scripts/.
OUT_DIR = Path(__file__).resolve().parent.parent / "public" / "icons"


def load_bold_font(target_px: int) -> ImageFont.FreeTypeFont:
    """Try a few common bold sans-serif paths; fall back to default."""
    candidates = [
        "DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "Arial Bold.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, target_px)
        except (OSError, IOError):
            continue
    # Default bitmap font is tiny but lets us at least produce *something*.
    return ImageFont.load_default()


def render_icon(size: int, padding_pct: float, out_path: Path) -> None:
    """Render an icon of (size x size) with text occupying inner area.

    padding_pct: fraction of the canvas reserved as transparent margin per
    side. 0.0 means edge-to-edge; 0.10 means 10% padding per side (so the
    text targets the inner 80% — the maskable spec recommendation).
    """
    img = Image.new("RGB", (size, size), BRAND)
    draw = ImageDraw.Draw(img)

    # Target font size: scale so the text height fills the inner area.
    inner = size * (1.0 - 2.0 * padding_pct)
    # Empirically ~0.7 of the inner box gives a comfortable "LD" cap-height
    # without crowding the edges. Using 0.62 to leave a touch more breathing
    # room around the descender of "D" / kerning of "L".
    font_px = max(8, int(inner * 0.62))
    font = load_bold_font(font_px)

    # Anchor 'mm' = middle/middle, so xy is the visual center of the text.
    cx, cy = size / 2, size / 2
    try:
        draw.text((cx, cy), TEXT, fill=WHITE, font=font, anchor="mm")
    except (TypeError, ValueError):
        # Default font doesn't support anchor; fall back to bbox math.
        bbox = draw.textbbox((0, 0), TEXT, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        draw.text((cx - tw / 2 - bbox[0], cy - th / 2 - bbox[1]),
                  TEXT, fill=WHITE, font=font)

    img.save(out_path, "PNG", optimize=True)
    print(f"  wrote {out_path.name} ({out_path.stat().st_size} bytes)")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Generating PWA icons in {OUT_DIR}")
    # Standard icons: edge-to-edge text (no padding) since browsers don't
    # mask the non-maskable variants.
    render_icon(192, padding_pct=0.0, out_path=OUT_DIR / "icon-192.png")
    render_icon(512, padding_pct=0.0, out_path=OUT_DIR / "icon-512.png")
    # Maskable: text inscribed in inner 80% so masking doesn't clip.
    render_icon(512, padding_pct=0.10,
                out_path=OUT_DIR / "icon-maskable-512.png")
    print("Done.")


if __name__ == "__main__":
    main()
