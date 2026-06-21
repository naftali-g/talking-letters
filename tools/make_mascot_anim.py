# -*- coding: utf-8 -*-
"""
make_mascot_anim.py — OFFLINE (not shipped). Builds the animated celebration mascot
from jumping_logo.mp4 into the project root, next to index.html:
  - mascot_anim.webp : transparent, looping animation of just the bubble mascot,
                       cropped to its jump and with the cream background + moving
                       contact shadow keyed out. The wordmark/tagline in the video
                       are excluded (they sit below the bubble's travel).

It plays automatically in a plain <img> tag (animated WebP), so the success view
needs no <video>/JS — same as the static mascot.webp it sits beside.

Requires PyAV for mp4 decoding:  pip install av   (plus numpy / scipy / Pillow).
Run:  python3 tools/make_mascot_anim.py
"""
import os
import av
import numpy as np
from scipy import ndimage
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "jumping_logo.mp4")
OUT = os.path.join(ROOT, "mascot_anim.webp")

STRIDE = 1       # keep every Nth frame — 1 = full ~24fps (smoothest); 2 ≈ 12fps & ~half the size
MAXDIM = 200     # display is 124px; this is comfortably retina-crisp
QUALITY = 76
PAD = 12         # transparent breathing room around the bubble's travel

# ---- decode all frames (RGB) ----
container = av.open(SRC)
fps = float(container.streams.video[0].average_rate)
frames = np.array([f.to_ndarray(format="rgb24") for f in container.decode(video=0)])
container.close()
N, H, W, _ = frames.shape

# ---- background cream: median of all four corners across every frame ----
corners = np.concatenate([frames[:, :40, :40], frames[:, :40, -40:],
                          frames[:, -40:, :40], frames[:, -40:, -40:]], 1).reshape(-1, 3)
cream = np.median(corners, 0)

# ---- per frame: the bubble is the largest non-cream blob; the wordmark letters are
#      separate, smaller components, so "largest component" isolates the bubble (the
#      same trick make_assets.py uses for the alef). Fill holes so eyes/mouth stay solid.
sils, diffs = [], []
y0, y1, x0, x1 = H, 0, W, 0
for fr in frames:
    diff = np.abs(fr.astype(np.int16) - cream).max(2).astype(np.float32)
    lbl, n = ndimage.label(diff > 45, np.ones((3, 3)))          # >45 excludes the faint shadow
    sizes = ndimage.sum(np.ones_like(lbl), lbl, range(1, n + 1))
    sil = ndimage.binary_fill_holes(lbl == (int(np.argmax(sizes)) + 1))
    sils.append(sil); diffs.append(diff)
    ys, xs = np.where(sil)                                       # union bbox so the jump never clips
    y0, y1 = min(y0, ys.min()), max(y1, ys.max())
    x0, x1 = min(x0, xs.min()), max(x1, xs.max())
y0, x0 = max(y0 - PAD, 0), max(x0 - PAD, 0)
y1, x1 = min(y1 + PAD, H), min(x1 + PAD, W)

# ---- build RGBA frames: feathered edge alpha, masked by the (slightly grown) silhouette
#      so the cream AND its moving shadow drop out but the bubble's soft rim survives ----
out = []
dur = int(round(1000.0 / fps * STRIDE))
for i in range(0, N, STRIDE):
    sil = ndimage.binary_dilation(sils[i], iterations=3)
    alpha = np.clip(np.clip((diffs[i] - 12) / 30, 0, 1) * sil, 0, 1)
    rgba = np.dstack([frames[i, y0:y1, x0:x1], (alpha[y0:y1, x0:x1] * 255).astype(np.uint8)])
    im = Image.fromarray(rgba, "RGBA")
    im.thumbnail((MAXDIM, MAXDIM), Image.LANCZOS)
    out.append(im)

out[0].save(OUT, "WEBP", save_all=True, append_images=out[1:],
            duration=dur, loop=0, quality=QUALITY, method=6)
print(f"  mascot_anim.webp: {round(os.path.getsize(OUT)/1024,1)} KB "
      f"({len(out)} frames @ {dur}ms, {out[0].size[0]}x{out[0].size[1]})")
