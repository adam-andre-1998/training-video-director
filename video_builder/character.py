"""The cartoon presenter: a woman seated in an office chair at a desk, drawn in code.

The character is built from layers (chair, back hair, body, head, desk, hands)
that are drawn once and composited every frame. That allows:

- lip sync: the mouth opens with the loudness of the narration at that moment;
- blinking at natural, irregular intervals;
- breathing, a slow head sway, and small nods while talking.

All shapes are in "design units" on a W x H canvas and drawn at SS x scale
for smooth edges.
"""

import functools
import math
import random
from typing import NamedTuple

import cv2
import numpy as np
from PIL import Image, ImageDraw

W, H = 900, 1000
SS = 3

# Palette (RGB, as PIL uses).
SKIN = (243, 197, 163)
SKIN_SHADE = (226, 170, 137)
HAIR = (72, 46, 38)
HAIR_LIGHT = (104, 70, 55)
BLAZER = (47, 88, 152)
BLAZER_SHADE = (36, 68, 120)
SHIRT = (248, 248, 252)
COLLAR = (232, 234, 242)
CHAIR = (50, 54, 64)
CHAIR_LIGHT = (66, 71, 84)
DESK_TOP = (214, 175, 132)
DESK_FRONT = (186, 145, 104)
DESK_EDGE = (160, 122, 86)
INK = (50, 36, 40)
LIPS = (186, 82, 92)
MOUTH = (112, 38, 50)
TONGUE = (226, 118, 128)
BLUSH = (238, 140, 140, 70)

DESK_Y, DESK_FRONT_Y = 845, 885   # top edge of the desk surface, and where its front starts
NECK_PIVOT = (450, 505)           # the head tilts around this point
HEAD_BOX = (280, 170, 620, 560)   # area the head layers are cropped to (x0, y0, x1, y1)
BOX = (0, 160, W, H)              # area every frame is cropped to: from just above the head down
PORTRAIT = (240, 180, 660, 600)   # head and shoulders, for the picture-in-picture circle


class Sprite(NamedTuple):
    """A layer cropped to its visible area: premultiplied BGR and alpha (float32, 0..1) at (x, y)."""
    bgr: np.ndarray
    alpha: np.ndarray
    x: int
    y: int


class _Layer:
    """A transparent canvas with drawing helpers in design units."""

    def __init__(self):
        self.img = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)

    @staticmethod
    def _s(values):
        return [v * SS for v in values]

    def ellipse(self, cx, cy, rx, ry, fill):
        self.d.ellipse(self._s((cx - rx, cy - ry, cx + rx, cy + ry)), fill=fill)

    def rect(self, x0, y0, x1, y1, fill, r=0):
        if r:
            self.d.rounded_rectangle(self._s((x0, y0, x1, y1)), radius=r * SS, fill=fill)
        else:
            self.d.rectangle(self._s((x0, y0, x1, y1)), fill=fill)

    def poly(self, points, fill):
        self.d.polygon([(x * SS, y * SS) for x, y in points], fill=fill)

    def line(self, points, fill, width):
        pts = [(x * SS, y * SS) for x, y in points]
        self.d.line(pts, fill=fill, width=int(width * SS), joint="curve")
        for x, y in (pts[0], pts[-1]):  # round caps
            r = width * SS / 2
            self.d.ellipse((x - r, y - r, x + r, y + r), fill=fill)

    def arc(self, cx, cy, rx, ry, start, end, fill, width):
        self.d.arc(self._s((cx - rx, cy - ry, cx + rx, cy + ry)), start, end, fill=fill, width=int(width * SS))

    def pieslice(self, cx, cy, rx, ry, start, end, fill):
        self.d.pieslice(self._s((cx - rx, cy - ry, cx + rx, cy + ry)), start, end, fill=fill)

    def overlay(self, draw):
        """Draws semi-transparent shapes: `draw` gets a fresh layer, which is alpha-composited on top."""
        top = _Layer()
        draw(top)
        self.img = Image.alpha_composite(self.img, top.img)
        self.d = ImageDraw.Draw(self.img)

    def done(self, box=None):
        """The layer at 1x as a Sprite, cropped to `box` (x0, y0, x1, y1) or else to what was drawn."""
        img = self.img.resize((W, H), Image.LANCZOS)
        box = box or img.getbbox() or (0, 0, 1, 1)
        arr = np.asarray(img.crop(box)).astype(np.float32) / 255
        alpha = np.ascontiguousarray(arr[..., 3])
        bgr = arr[..., [2, 1, 0]] * alpha[..., None]
        return Sprite(bgr, alpha, box[0], box[1])


# ------------------------------------------------------------------ static parts
def draw_desk(layer, x0, x1, top=DESK_Y, front=DESK_FRONT_Y, bottom=H):
    """Desk surface and front. Also used for the full-width desk in the office backdrop."""
    layer.rect(x0, top, x1, front, DESK_TOP)
    layer.rect(x0, front, x1, bottom, DESK_FRONT)
    layer.rect(x0, front, x1, front + 6, DESK_EDGE)


def _chair():
    L = _Layer()
    L.rect(245, 300, 655, 880, CHAIR, r=80)
    L.rect(272, 326, 628, 850, CHAIR_LIGHT, r=62)
    L.rect(300, 350, 600, 830, CHAIR, r=50)
    return L.done()


def _back_hair():
    L = _Layer()
    L.ellipse(450, 345, 138, 150, HAIR)
    L.rect(318, 340, 582, 505, HAIR, r=60)
    return L.done(HEAD_BOX)


def _body():
    L = _Layer()
    L.rect(418, 455, 482, 570, SKIN)                     # neck
    L.ellipse(450, 484, 34, 22, SKIN_SHADE)              # shadow under the chin
    L.rect(272, 538, 628, 960, BLAZER, r=96)             # torso and shoulders
    L.poly([(398, 542), (502, 542), (450, 672)], SHIRT)  # shirt
    L.poly([(418, 534), (482, 534), (450, 600)], SKIN)   # open collar
    L.poly([(398, 542), (418, 536), (446, 612), (424, 618)], COLLAR)
    L.poly([(502, 542), (482, 536), (454, 612), (476, 618)], COLLAR)
    L.line([(392, 554), (450, 684)], BLAZER_SHADE, 7)    # lapels
    L.line([(508, 554), (450, 684)], BLAZER_SHADE, 7)
    L.ellipse(450, 770, 7, 7, BLAZER_SHADE)              # buttons
    L.ellipse(450, 818, 7, 7, BLAZER_SHADE)
    L.line([(300, 610), (290, 830)], BLAZER_SHADE, 6)    # arm seams
    L.line([(600, 610), (610, 830)], BLAZER_SHADE, 6)
    return L.done()


def _front():
    """The desk with a mug and a plant, and the forearms and hands resting on it."""
    L = _Layer()
    draw_desk(L, 0, W)
    # Plant.
    for dx, dy, rx, ry, color in ((-26, -60, 22, 46, (80, 150, 92)), (24, -58, 22, 44, (70, 138, 84)),
                                  (0, -80, 20, 50, (92, 168, 104)), (-44, -30, 18, 34, (70, 138, 84)),
                                  (44, -30, 18, 34, (80, 150, 92))):
        L.ellipse(150 + dx, 820 + dy, rx, ry, color)
    L.poly([(112, 800), (188, 800), (178, 858), (122, 858)], (198, 112, 80))
    L.rect(106, 790, 194, 806, (210, 124, 90), r=4)
    # Mug.
    L.arc(754, 818, 22, 20, 270, 90, (236, 236, 242), 9)
    L.rect(690, 786, 752, 858, (236, 236, 242), r=10)
    L.ellipse(721, 790, 31, 8, (120, 82, 60))
    L.rect(704, 812, 738, 832, BLAZER, r=4)
    # Forearms and hands.
    for side in (-1, 1):
        elbow = (450 + side * 160, 842)
        wrist = (450 + side * 52, 878)
        L.line([elbow, wrist], BLAZER, 66)
        L.line([elbow, wrist], BLAZER_SHADE, 2)
        cuff_a = (wrist[0] + side * 4, wrist[1] - 2)
        L.line([cuff_a, (wrist[0] - side * 6, wrist[1])], SHIRT, 60)
    L.ellipse(426, 882, 40, 26, SKIN_SHADE)
    L.ellipse(474, 882, 40, 26, SKIN_SHADE)
    L.ellipse(428, 878, 37, 23, SKIN)
    L.ellipse(472, 878, 37, 23, SKIN)
    L.line([(436, 868), (464, 868)], SKIN_SHADE, 3)
    return L.done()


# --------------------------------------------------------------------- the head
@functools.lru_cache(maxsize=None)
def _head(mouth, round_mouth, blink, brows):
    """The face for one expression: mouth 0 (closed) to 5 (wide open), blink 0 (open) to 2 (closed),
    brows 0 (rest) or 1 (raised)."""
    L = _Layer()
    L.ellipse(332, 372, 17, 28, SKIN_SHADE)    # ears
    L.ellipse(568, 372, 17, 28, SKIN_SHADE)
    L.ellipse(450, 365, 112, 132, SKIN)        # face

    def blush(top):
        top.ellipse(382, 425, 24, 14, BLUSH)
        top.ellipse(518, 425, 24, 14, BLUSH)
    L.overlay(blush)

    # Hair: top of the head and a side-swept fringe.
    L.pieslice(450, 302, 126, 86, 180, 360, HAIR)
    L.poly([(326, 340), (338, 296), (380, 258), (450, 242), (520, 252), (566, 296), (576, 340),
            (560, 346), (544, 300), (490, 280), (420, 290), (372, 310), (348, 346), (330, 360)], HAIR)
    L.line([(392, 264), (470, 250)], HAIR_LIGHT, 5)

    # Brows.
    lift = 7 if brows else 0
    L.line([(386, 330 - lift), (408, 324 - lift), (428, 328 - lift)], HAIR, 7)
    L.line([(472, 328 - lift), (492, 324 - lift), (514, 330 - lift)], HAIR, 7)

    # Eyes.
    for ex in (407, 493):
        if blink >= 2:
            L.arc(ex, 368, 14, 8, 20, 160, INK, 5)
        else:
            ry = 16 if blink == 0 else 8
            L.ellipse(ex, 372, 11, ry, INK)
            if blink == 0:
                L.ellipse(ex + 4, 366, 4, 4, (255, 255, 255))
            L.line([(ex + 10, 360), (ex + 17, 354)], INK, 3)   # lash

    # Nose.
    L.arc(452, 402, 10, 16, 300, 60, SKIN_SHADE, 5)

    # Mouth.
    cx, cy = 450, 452
    if mouth == 0:
        L.arc(cx, cy - 10, 26, 16, 25, 155, LIPS, 6)
    elif round_mouth:
        rx, ry = 10 + 3 * mouth, 7 + 5 * mouth
        L.ellipse(cx, cy + ry * 0.4, rx + 3, ry + 3, LIPS)
        L.ellipse(cx, cy + ry * 0.4, rx, ry, MOUTH)
    else:
        rx, ry = 22 + 4 * mouth, 5 + 6 * mouth
        L.pieslice(cx, cy - 2, rx + 3, ry + 3, 0, 180, LIPS)
        L.pieslice(cx, cy - 2, rx, ry, 0, 180, MOUTH)
        L.rect(cx - rx * 0.75, cy - 2, cx + rx * 0.75, cy - 2 + min(ry * 0.35, 9), (255, 255, 255))
        if mouth >= 3:
            L.ellipse(cx, cy - 2 + ry * 0.75, rx * 0.45, ry * 0.25, TONGUE)
    return L.done(HEAD_BOX)


# ------------------------------------------------------------------- compositing
def _over(dst_bgr, dst_a, sprite, dx=0, dy=0):
    """Premultiplied "over": puts a sprite onto the W x H canvas, shifted by (dx, dy)."""
    src_bgr, src_a, x, y = sprite
    x, y = x + dx, y + dy
    h, w = src_a.shape
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, W), min(y + h, H)
    if x0 >= x1 or y0 >= y1:
        return
    s_a = src_a[y0 - y:y1 - y, x0 - x:x1 - x]
    inv = 1 - s_a
    dst_bgr[y0:y1, x0:x1] = src_bgr[y0 - y:y1 - y, x0 - x:x1 - x] + dst_bgr[y0:y1, x0:x1] * inv[..., None]
    dst_a[y0:y1, x0:x1] = s_a + dst_a[y0:y1, x0:x1] * inv


def _tilt(sprite, angle):
    """Rotates a head-box sprite by `angle` degrees around the neck pivot."""
    if abs(angle) < 0.05:
        return sprite
    px, py = NECK_PIVOT[0] - sprite.x, NECK_PIVOT[1] - sprite.y
    m = cv2.getRotationMatrix2D((px, py), angle, 1.0)
    size = (sprite.alpha.shape[1], sprite.alpha.shape[0])
    return Sprite(cv2.warpAffine(sprite.bgr, m, size, flags=cv2.INTER_LINEAR),
                  cv2.warpAffine(sprite.alpha, m, size, flags=cv2.INTER_LINEAR), sprite.x, sprite.y)


class Character:
    """Renders the presenter for a given time and narration loudness."""

    def __init__(self, seed=7):
        self.chair = _chair()
        self.back_hair = _back_hair()
        self.body = _body()
        self.front = _front()
        rng = random.Random(seed)
        self.blinks = []  # start times of blinks
        t = 1.0
        while t < 3600:
            self.blinks.append(t)
            t += rng.uniform(2.2, 5.5)

    def _blink(self, t):
        i = np.searchsorted(self.blinks, t) - 1
        if i < 0:
            return 0
        k = t - self.blinks[i]
        return 1 if k < 0.05 else 2 if k < 0.13 else 1 if k < 0.18 else 0

    def frame(self, t, loudness=0.0, talking_level=0.0):
        """The character as (premultiplied BGR float32, alpha float32), cropped to BOX.

        t: time in seconds (drives breathing, sway and blinks).
        loudness: narration loudness 0..1 at this moment (drives the mouth).
        talking_level: 0..1, how much "talking" head motion to add (smoothed by the caller).
        """
        breath = 3 * math.sin(2 * math.pi * t / 4.2)
        sway = 1.4 * math.sin(2 * math.pi * t / 6.3)
        nod = talking_level * (2.2 * math.sin(2 * math.pi * t / 1.9) + 1.2 * math.sin(2 * math.pi * t / 0.83))
        angle = sway + nod
        head_dy = int(round(breath * 0.8 - 5 * loudness))
        body_dy = int(round(breath))

        mouth = int(round(min(loudness, 1.0) ** 0.8 * 5))
        round_mouth = mouth >= 2 and (int(t * 7) % 5 == 0)
        head = _head(mouth, round_mouth, self._blink(t), int(loudness > 0.8))

        bgr = np.zeros((H, W, 3), np.float32)
        alpha = np.zeros((H, W), np.float32)
        _over(bgr, alpha, self.chair)
        _over(bgr, alpha, _tilt(self.back_hair, angle), 0, head_dy)
        _over(bgr, alpha, self.body, 0, body_dy)
        _over(bgr, alpha, _tilt(head, angle), 0, head_dy)
        _over(bgr, alpha, self.front)
        x0, y0, x1, y1 = BOX
        return bgr[y0:y1, x0:x1], alpha[y0:y1, x0:x1]
