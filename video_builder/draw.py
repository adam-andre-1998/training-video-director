"""Low-level drawing helpers: easing, text images, alpha blending."""

import functools

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .config import FONT_BOLD, FONT_MONO, FONT_REGULAR


# ------------------------------------------------------------------ easing
def clamp01(x):
    return min(max(x, 0.0), 1.0)


def ease_out(x):
    x = clamp01(x)
    return 1 - (1 - x) ** 3


def smoothstep(x):
    x = clamp01(x)
    return x * x * (3 - 2 * x)


def fade(t, duration, fade_in=0.2, fade_out=0.2):
    """Opacity 0..1 for something visible from 0 to `duration`, with fades at both ends."""
    if t < 0 or t > duration:
        return 0.0
    return min(clamp01(t / fade_in) if fade_in else 1.0,
               clamp01((duration - t) / fade_out) if fade_out else 1.0)


# -------------------------------------------------------------------- text
@functools.lru_cache(maxsize=None)
def font(kind, size):
    path = {"bold": FONT_BOLD, "mono": FONT_MONO}.get(kind, FONT_REGULAR)
    try:
        return ImageFont.truetype(str(path), size)
    except OSError:
        return ImageFont.load_default(size)


def _rgb(bgr):
    return (bgr[2], bgr[1], bgr[0])


@functools.lru_cache(maxsize=512)
def text_box(text, size, color, bg=None, kind="regular", pad=(0, 0), radius=0, border=None):
    """Renders text (optionally on a rounded box) to a BGRA image."""
    f = font(kind, size)
    left, top, right, bottom = f.getbbox(text or " ")
    ascent, descent = f.getmetrics()
    w = right - left + 2 * pad[0]
    h = ascent + descent + 2 * pad[1]
    img = Image.new("RGBA", (max(w, 1), max(h, 1)), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if bg is not None:
        fill = _rgb(bg[:3]) + ((bg[3],) if len(bg) == 4 else (255,))
        outline = _rgb(border[:3]) if border else None
        d.rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=fill,
                            outline=outline, width=3 if border else 0)
    d.text((pad[0] - left, pad[1]), text, font=f, fill=_rgb(color) + (255,))
    rgba = np.asarray(img)
    return np.ascontiguousarray(rgba[..., [2, 1, 0, 3]])


# --------------------------------------------------------------- blending
def blit(canvas, bgra, x, y, opacity=1.0):
    """Alpha-blends a BGRA image onto a BGR canvas with its top-left at (x, y)."""
    if opacity <= 0:
        return
    h, w = bgra.shape[:2]
    H, W = canvas.shape[:2]
    x, y = int(round(x)), int(round(y))
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, W), min(y + h, H)
    if x0 >= x1 or y0 >= y1:
        return
    src = bgra[y0 - y:y1 - y, x0 - x:x1 - x]
    a = src[..., 3:4].astype(np.float32) * (opacity / 255.0)
    dst = canvas[y0:y1, x0:x1]
    dst[:] = (src[..., :3] * a + dst * (1 - a)).astype(np.uint8)


def blit_masked(canvas, bgr, alpha, x, y):
    """Blends a BGR image with a float alpha mask (0..1, HxW) onto the canvas."""
    h, w = alpha.shape
    H, W = canvas.shape[:2]
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, W), min(y + h, H)
    if x0 >= x1 or y0 >= y1:
        return
    a = alpha[y0 - y:y1 - y, x0 - x:x1 - x, None]
    src = bgr[y0 - y:y1 - y, x0 - x:x1 - x]
    dst = canvas[y0:y1, x0:x1]
    dst[:] = (src * a + dst * (1 - a)).astype(np.uint8)


def blit_premult(canvas, bgr, alpha, x, y):
    """Blends premultiplied float BGR (0..1) with its alpha (0..1, HxW) onto the canvas."""
    h, w = alpha.shape
    H, W = canvas.shape[:2]
    x, y = int(x), int(y)
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, W), min(y + h, H)
    if x0 >= x1 or y0 >= y1:
        return
    a = alpha[y0 - y:y1 - y, x0 - x:x1 - x, None]
    src = bgr[y0 - y:y1 - y, x0 - x:x1 - x]
    dst = canvas[y0:y1, x0:x1]
    dst[:] = np.clip(src * 255 + dst * (1 - a), 0, 255).astype(np.uint8)


def with_opacity(canvas, opacity, draw):
    """Runs `draw(img)` and blends the result onto the canvas at `opacity`."""
    if opacity <= 0:
        return
    if opacity >= 0.999:
        draw(canvas)
        return
    layer = canvas.copy()
    draw(layer)
    cv2.addWeighted(layer, opacity, canvas, 1 - opacity, 0, dst=canvas)


def rounded_rect(img, x, y, w, h, r, color, thickness=-1):
    """Filled (thickness=-1) or outlined rounded rectangle, anti-aliased."""
    x, y, w, h, r = int(x), int(y), int(w), int(h), int(min(r, w / 2, h / 2))
    if thickness < 0:
        cv2.rectangle(img, (x + r, y), (x + w - r, y + h), color, -1)
        cv2.rectangle(img, (x, y + r), (x + w, y + h - r), color, -1)
        for cx, cy in ((x + r, y + r), (x + w - r, y + r), (x + r, y + h - r), (x + w - r, y + h - r)):
            cv2.circle(img, (cx, cy), r, color, -1, cv2.LINE_AA)
        return
    t = thickness
    cv2.line(img, (x + r, y), (x + w - r, y), color, t, cv2.LINE_AA)
    cv2.line(img, (x + r, y + h), (x + w - r, y + h), color, t, cv2.LINE_AA)
    cv2.line(img, (x, y + r), (x, y + h - r), color, t, cv2.LINE_AA)
    cv2.line(img, (x + w, y + r), (x + w, y + h - r), color, t, cv2.LINE_AA)
    for (cx, cy), start in (((x + r, y + r), 180), ((x + w - r, y + r), 270),
                            ((x + w - r, y + h - r), 0), ((x + r, y + h - r), 90)):
        cv2.ellipse(img, (cx, cy), (r, r), 0, start, start + 90, color, t, cv2.LINE_AA)
