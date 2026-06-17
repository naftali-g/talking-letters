# -*- coding: utf-8 -*-
"""
make_assets.py — OFFLINE (not shipped). Builds the deployable image assets from
logo.png into the project root, next to index.html:
  - logo.webp    : header logo (mascot + wordmark), cream background made transparent
  - favicon.png  : just the alef mascot on a cream square

Run:  python3 tools/make_assets.py
"""
import os
import numpy as np
from PIL import Image
from scipy import ndimage

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

im = Image.open(os.path.join(ROOT, "logo.png")).convert("RGB")
A = np.asarray(im).astype(np.int16)
H, W, _ = A.shape
cream = np.median(np.concatenate([A[:60, :60].reshape(-1, 3), A[:60, -60:].reshape(-1, 3),
                                  A[-60:, :60].reshape(-1, 3), A[-60:, -60:].reshape(-1, 3)]), 0)
mask = ndimage.binary_opening(np.abs(A - cream).max(2) > 28, np.ones((3, 3)), iterations=2)

# ---- header logo: full content, cream -> transparent (soft shadows kept as partial alpha) ----
ys, xs = np.where(mask)
pad = 42
y0, y1, x0, x1 = max(ys.min() - pad, 0), min(ys.max() + pad, H), max(xs.min() - pad, 0), min(xs.max() + pad, W)
crop = A[y0:y1, x0:x1].astype(np.float32)
alpha = np.clip((np.abs(crop - cream).max(2) - 6) / 26, 0, 1) * 255
rgba = np.dstack([np.clip(crop, 0, 255), alpha]).astype(np.uint8)
header = Image.fromarray(rgba, "RGBA")
header.thumbnail((560, 560), Image.LANCZOS)
header.save(os.path.join(ROOT, "logo.webp"), "WEBP", quality=86, method=6)

# ---- favicon: largest component (the alef mascot), centered on a cream square ----
lbl, n = ndimage.label(mask, np.ones((3, 3)))
sizes = ndimage.sum(np.ones_like(lbl), lbl, range(1, n + 1))
alef = int(np.argmax(sizes)) + 1
ys, xs = np.where(lbl == alef)
ax0, ay0, ax1, ay1 = xs.min(), ys.min(), xs.max(), ys.max()
aw, ah = ax1 - ax0, ay1 - ay0
side = int(max(aw, ah) * 1.22)
canvas = Image.new("RGB", (side, side), tuple(int(c) for c in cream))
canvas.paste(im.crop((ax0, ay0, ax1 + 1, ay1 + 1)), ((side - aw) // 2, (side - ah) // 2))
canvas.resize((128, 128), Image.LANCZOS).save(os.path.join(ROOT, "favicon.png"), optimize=True)

# ---- mascot.webp: alef only, transparent background (for the celebration overlay) ----
mp = 18
mx0, my0, mx1, my1 = max(ax0 - mp, 0), max(ay0 - mp, 0), min(ax1 + mp, W), min(ay1 + mp, H)
mc = A[my0:my1, mx0:mx1].astype(np.float32)
malpha = np.clip((np.abs(mc - cream).max(2) - 6) / 26, 0, 1) * 255
mascot = Image.fromarray(np.dstack([np.clip(mc, 0, 255), malpha]).astype(np.uint8), "RGBA")
mascot.thumbnail((320, 320), Image.LANCZOS)
mascot.save(os.path.join(ROOT, "mascot.webp"), "WEBP", quality=88, method=6)

for f in ("logo.webp", "favicon.png", "mascot.webp"):
    print(f"  {f}: {round(os.path.getsize(os.path.join(ROOT, f))/1024,1)} KB")
