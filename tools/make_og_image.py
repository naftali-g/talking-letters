# -*- coding: utf-8 -*-
"""
make_og_image.py — OFFLINE (the OUTPUT ships). Builds the social-share / Open
Graph card og-image.png (1200x630, the 1.91:1 size Facebook / WhatsApp / Slack /
X expect) from logo.webp on the brand-colored background.

Why a dedicated image: none of the existing assets fit OG — logo.png is 2048x2048
and 3.2MB, logo.webp is portrait 757x1000, mascot.webp is tiny, and og:image
should be PNG/JPG (not WebP). This composes a proper landscape card.

The card is intentionally TEXT-FREE: the share preview's caption (og:title +
og:description, plain Hebrew) is rendered by the platform directly under the
image, so baking text into the pixels would be redundant and crop-fragile. The
image is just the brand: the mascot + niqqud wordmark + tagline (already in
logo.webp) centered on the site's cream/gradient background.

Run:  python3 tools/make_og_image.py        # -> ../og-image.png
"""
import os
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

W, H = 1200, 630
CREAM = (255, 249, 240)      # --cream
ORANGE = (255, 241, 224)     # radial top-right tint (matches body bg)
BLUE = (232, 246, 255)       # radial top-left tint


def radial(cx, cy, rx, ry):
    """Normalized 0..1 radial falloff (1 at center, 0 at/after the ellipse edge)."""
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.sqrt(((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2)
    return np.clip(1.0 - d, 0.0, 1.0)


def build_background():
    base = np.empty((H, W, 3), np.float32)
    base[:] = CREAM
    # two soft radial tints, mirroring the site's body background (orange + blue)
    for tint, geo in ((ORANGE, (W * 1.0, -30, 820, 470)), (BLUE, (-40, 30, 760, 420))):
        a = radial(*geo)[..., None]
        base = base * (1 - a) + np.array(tint, np.float32) * a
    return Image.fromarray(np.clip(base, 0, 255).astype(np.uint8), "RGB")


def main():
    img = build_background()

    # mascot + niqqud wordmark + tagline, centered as a brand emblem
    logo = Image.open(os.path.join(ROOT, "logo.webp")).convert("RGBA")
    target_h = 540
    scale = target_h / logo.height
    logo = logo.resize((round(logo.width * scale), target_h), Image.LANCZOS)
    img.paste(logo, ((W - logo.width) // 2, (H - logo.height) // 2), logo)

    out = os.path.join(ROOT, "og-image.png")
    img.save(out, "PNG", optimize=True)
    kb = os.path.getsize(out) / 1024
    print(f"  og-image.png: {W}x{H}  {kb:.1f} KB")


if __name__ == "__main__":
    main()
