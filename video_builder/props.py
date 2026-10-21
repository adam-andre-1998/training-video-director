"""Drawing the timeline's props (arrows, ripples, highlight boxes, callouts, key badges, captions).

Each prop function takes the canvas, the prop dict, the time since the prop
started, and a PropContext. Sizes are given for 1920x1080 and scaled by
`ctx.s` for other output sizes.
"""

import math
from dataclasses import dataclass

import cv2
import numpy as np

from .config import ACCENT, CAPTION_BG, HIGHLIGHT, INK, WHITE
from .draw import blit, ease_out, fade, rounded_rect, text_box, with_opacity

DIRECTIONS = {
    "top": (0, -1), "bottom": (0, 1), "left": (-1, 0), "right": (1, 0),
    "top-left": (-1, -1), "top-right": (1, -1), "bottom-left": (-1, 1), "bottom-right": (1, 1),
}
# Props drawn first end up underneath the others.
DRAW_ORDER = ["highlight_box", "click_ripple", "arrow", "callout", "typing_caption", "key_badge"]


@dataclass
class PropContext:
    width: int
    height: int
    s: float               # output scale relative to 1920x1080
    view: object = None    # layout.ScreenView on screen segments, else None
    segment: object = None
    events: dict = None    # recording events by id

    def point(self, xy):
        """Canvas position of a recording coordinate, or None if it's off screen."""
        if self.view is None or not self.view.visible(*xy):
            return None
        return self.view.to_canvas(*xy)

    def screen_box(self):
        """(x, y, w, h) of the visible recording on the canvas, or the whole canvas."""
        if self.view is None:
            return 0, 0, self.width, self.height
        v = self.view
        return v.dx, v.dy, v.dw, v.dh


def draw_props(canvas, props, t, ctx):
    for kind in DRAW_ORDER:
        for p in props:
            if p["type"] == kind and p["start"] <= t <= p["start"] + p["duration"]:
                DRAWERS[kind](canvas, p, t - p["start"], ctx)


# ------------------------------------------------------------------ arrow
def arrow(canvas, p, local, ctx):
    tip_target = ctx.point(p["target"])
    if tip_target is None:
        return
    s = ctx.s
    dx, dy = DIRECTIONS.get(p.get("from", "bottom-right"), (1, 1))
    norm = math.hypot(dx, dy)
    dx, dy = dx / norm, dy / norm
    # Slides in towards the target, then bobs gently.
    gap = (8 + (1 - ease_out(local / 0.3)) * 70 + 7 * math.sin(local * 2 * math.pi * 1.4)) * s
    tip = np.array([tip_target[0] + dx * gap, tip_target[1] + dy * gap])
    d = np.array([dx, dy])
    perp = np.array([-dy, dx])
    head_len, head_w, length = 48 * s, 32 * s, 150 * s
    neck = tip + d * head_len
    tail = tip + d * length

    def draw(img):
        for color, grow in ((WHITE, 6 * s), (ACCENT, 0)):
            t_ = max(int(18 * s + 2 * grow), 1)
            cv2.line(img, tuple(np.int32(neck - d * grow * 0.3)), tuple(np.int32(tail + d * grow)), color, t_, cv2.LINE_AA)
            head = np.array([tip - d * grow * 1.6, neck + perp * (head_w + grow), neck - perp * (head_w + grow)], np.int32)
            cv2.fillPoly(img, [head], color, cv2.LINE_AA)

    opacity = fade(local, p["duration"], 0.15, 0.2)
    with_opacity(canvas, opacity, draw)
    if p.get("label"):
        box = text_box(p["label"], int(30 * s), WHITE, bg=ACCENT, kind="bold",
                       pad=(int(16 * s), int(6 * s)), radius=int(18 * s), border=WHITE)
        h, w = box.shape[:2]
        # Put the label just beyond the tail, on the side the arrow comes from.
        cx = tail[0] + dx * (w / 2 + 10 * s)
        cy = tail[1] + dy * (h / 2 + 10 * s)
        blit(canvas, box, cx - w / 2, cy - h / 2, opacity)


# ----------------------------------------------------------- click ripple
def click_ripple(canvas, p, local, ctx):
    pt = ctx.point(p["target"])
    if pt is None:
        return
    s = ctx.s
    k = local / max(p["duration"], 0.01)
    center = (int(pt[0]), int(pt[1]))
    for delay in (0.0, 0.25):
        kk = (k - delay) / (1 - delay)
        if 0 <= kk <= 1:
            r = int((14 + 56 * ease_out(kk)) * s)
            with_opacity(canvas, 1 - kk, lambda img: cv2.circle(img, center, r, ACCENT, max(int(6 * s), 1), cv2.LINE_AA))
    with_opacity(canvas, 1 - k, lambda img: cv2.circle(img, center, int(10 * s), ACCENT, -1, cv2.LINE_AA))


# ---------------------------------------------------------- highlight box
def highlight_box(canvas, p, local, ctx):
    x, y, w, h = p["box"]
    a, b = ctx.point((x, y)), ctx.point((x + w, y + h))
    if ctx.view is not None:  # the box may be partly off screen when zoomed
        a = a or ctx.view.to_canvas(x, y)
        b = b or ctx.view.to_canvas(x + w, y + h)
    if a is None or b is None:
        return
    s = ctx.s
    opacity = fade(local, p["duration"], 0.3, 0.3)
    pad = 6 * s
    x0, y0, x1, y1 = int(a[0] - pad), int(a[1] - pad), int(b[0] + pad), int(b[1] + pad)

    # Dim the rest of the screen.
    sx, sy, sw, sh = ctx.screen_box()
    region = canvas[sy:sy + sh, sx:sx + sw]
    keep = region[max(y0 - sy, 0):max(y1 - sy, 0), max(x0 - sx, 0):max(x1 - sx, 0)].copy()
    region[:] = (region * (1 - 0.45 * opacity)).astype(np.uint8)
    region[max(y0 - sy, 0):max(y1 - sy, 0), max(x0 - sx, 0):max(x1 - sx, 0)] = keep

    with_opacity(canvas, opacity, lambda img: rounded_rect(img, x0, y0, x1 - x0, y1 - y0, 10 * s, HIGHLIGHT, max(int(5 * s), 1)))
    if p.get("label"):
        box = text_box(p["label"], int(28 * s), INK, bg=HIGHLIGHT, kind="bold",
                       pad=(int(14 * s), int(5 * s)), radius=int(12 * s))
        bh = box.shape[0]
        ly = y0 - bh - 8 * s if y0 - bh - 8 * s > sy else y1 + 8 * s
        blit(canvas, box, x0, ly, opacity)


# ---------------------------------------------------------------- callout
ANCHORS = {
    "top": (0.5, 0.0), "bottom": (0.5, 1.0), "center": (0.5, 0.5),
    "top-left": (0.0, 0.0), "top-right": (1.0, 0.0), "bottom-left": (0.0, 1.0), "bottom-right": (1.0, 1.0),
}


def callout(canvas, p, local, ctx):
    s = ctx.s
    opacity = fade(local, p["duration"], 0.25, 0.25)
    rise = (1 - ease_out(local / 0.3)) * 20 * s
    box = text_box(p["text"], int(34 * s), INK, bg=WHITE, kind="bold",
                   pad=(int(24 * s), int(14 * s)), radius=int(20 * s), border=ACCENT)
    h, w = box.shape[:2]
    margin = 40 * s

    if "target" in p:
        pt = ctx.point(p["target"])
        if pt is None:
            return
        sx, sy, sw, sh = ctx.screen_box()
        above = pt[1] - h - 50 * s > sy
        inset = 12 * s  # keep the bubble on the laptop screen
        x = min(max(pt[0] - w / 2, sx + inset), sx + sw - w - inset)
        y = pt[1] - h - 40 * s if above else pt[1] + 40 * s
        base_y = y + h - 2 if above else y + 2
        tail = np.array([[pt[0] - 14 * s, base_y], [pt[0] + 14 * s, base_y],
                         [pt[0], pt[1] - 8 * s if above else pt[1] + 8 * s]], np.int32)
        with_opacity(canvas, opacity, lambda img: cv2.fillPoly(img, [tail], ACCENT, cv2.LINE_AA))
        blit(canvas, box, x, y + rise, opacity)
        return

    sx, sy, sw, sh = ctx.screen_box()
    ax, ay = ANCHORS.get(p.get("anchor", "top"), (0.5, 0.0))
    x = sx + margin + ax * (sw - w - 2 * margin)
    y = sy + margin + ay * (sh - h - 2 * margin)
    blit(canvas, box, x, y + rise, opacity)


# -------------------------------------------------------------- key badge
def key_badge(canvas, p, local, ctx):
    s = ctx.s
    opacity = fade(local, p["duration"], 0.15, 0.25)
    keys = [text_box(k, int(44 * s), INK, bg=(246, 246, 246), kind="bold", pad=(int(26 * s), int(10 * s)),
                     radius=int(14 * s), border=(175, 175, 175)) for k in p["keys"]]
    plus = text_box("+", int(44 * s), WHITE, kind="bold")
    parts = []
    for i, k in enumerate(keys):
        if i:
            parts.append(plus)
        parts.append(k)
    gap = int(14 * s)
    total = sum(img.shape[1] for img in parts) + gap * (len(parts) - 1)
    height = max(img.shape[0] for img in parts)
    sx, sy, sw, sh = ctx.screen_box()
    x = sx + (sw - total) / 2
    y = sy + sh - height - 50 * s + (1 - ease_out(local / 0.2)) * 20 * s

    # Dark plate behind the keys so they read on any background.
    pad = 18 * s
    with_opacity(canvas, opacity * 0.75, lambda img: rounded_rect(
        img, x - pad, y - pad, total + 2 * pad, height + 2 * pad, 20 * s, CAPTION_BG))
    for img in parts:
        blit(canvas, img, x, y + (height - img.shape[0]) / 2, opacity)
        x += img.shape[1] + gap


# --------------------------------------------------------- typing caption
def typing_caption(canvas, p, local, ctx):
    s = ctx.s
    text = " ".join(p["text"].split())
    seg = ctx.segment
    # Reveal the text as it is typed: in time with the recorded typing when we know it.
    ev = ctx.events.get(p.get("event_id")) if ctx.events else None
    if ev is not None and ev.get("action") == "type" and seg.type == "screen_recording":
        t0 = seg.event_time(ev, "start_timestamp") - p["start"]
        t1 = seg.event_time(ev, "end_timestamp") - p["start"]
    else:
        t0, t1 = 0.0, p["duration"] * 0.6
    shown = len(text) if local >= t1 else int(len(text) * max(local - t0, 0) / max(t1 - t0, 0.01))
    caret = "|" if (local * 2) % 1 < 0.5 or local < t1 else " "
    box = text_box(text[:shown] + caret, int(46 * s), WHITE, bg=CAPTION_BG + (235,), kind="mono",
                   pad=(int(28 * s), int(14 * s)), radius=int(16 * s))
    # Keep the box centered on the full text's width so it doesn't jump while typing.
    full_w = text_box(text + "|", int(46 * s), WHITE, kind="mono", pad=(int(28 * s), int(14 * s))).shape[1]
    sx, sy, sw, sh = ctx.screen_box()
    x = sx + (sw - full_w) / 2
    y = sy + sh - box.shape[0] - 50 * s
    blit(canvas, box, x, y, fade(local, p["duration"], 0.15, 0.25))


DRAWERS = {
    "arrow": arrow, "click_ripple": click_ripple, "highlight_box": highlight_box,
    "callout": callout, "key_badge": key_badge, "typing_caption": typing_caption,
}
