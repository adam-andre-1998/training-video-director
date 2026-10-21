"""The static scenery (backdrop and laptop) and mapping recordings onto the laptop screen."""

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from . import character
from .config import BACKDROP_BOTTOM, BACKDROP_TOP
from .draw import smoothstep


def gradient(width, height, top, bottom):
    t = np.linspace(0, 1, height, dtype=np.float32)[:, None, None]
    img = np.array(top, np.float32) * (1 - t) + np.array(bottom, np.float32) * t
    return np.repeat(img, width, axis=1).astype(np.uint8)


class Stage:
    """Pre-rendered backgrounds shared by every frame.

    - `backdrop`: a plain gradient for title cards.
    - `laptop`: the backdrop with a laptop whose screen area is `screen`
      (x, y, w, h). Screen segments draw the recording into that area.
    - `office`: the room the presenter sits in, with a full-width desk lined
      up with the character's own desk at `presenter` = (scale, x, y), the
      size and top-left position of the character's frame.
    """

    def __init__(self, width, height):
        self.width, self.height = width, height
        self.backdrop = gradient(width, height, BACKDROP_TOP, BACKDROP_BOTTOM)
        self.screen, self.laptop = self._build_laptop()
        self.presenter, self.office = self._build_office()

    def _build_office(self):
        W, H = self.width, self.height
        s = W / 1920
        box_x0, box_y0, box_x1, box_y1 = character.BOX
        k = 1.12 * s
        px = int((W - (box_x1 - box_x0) * k) / 2)
        py = int(H - (box_y1 - box_y0) * k)

        img = Image.fromarray(gradient(W, H, (216, 226, 234), (196, 208, 218))[..., ::-1].copy())
        d = ImageDraw.Draw(img)
        # Window with sky and clouds.
        wx0, wy0, wx1, wy1 = 150 * s, 140 * s, 600 * s, 620 * s
        d.rounded_rectangle((wx0 - 16 * s, wy0 - 16 * s, wx1 + 16 * s, wy1 + 16 * s), radius=int(10 * s), fill=(246, 246, 246))
        sky = Image.fromarray(gradient(int(wx1 - wx0), int(wy1 - wy0), (240, 214, 170), (250, 236, 210))[..., ::-1].copy())
        img.paste(sky, (int(wx0), int(wy0)))
        for cx, cy, r in ((260, 260, 34), (300, 250, 44), (345, 262, 30), (470, 420, 28), (505, 412, 38), (540, 424, 26)):
            d.ellipse(((cx - r) * s, (cy - r * 0.7) * s, (cx + r) * s, (cy + r * 0.7) * s), fill=(255, 255, 255))
        d.rectangle(((wx0 + wx1) / 2 - 7 * s, wy0, (wx0 + wx1) / 2 + 7 * s, wy1), fill=(246, 246, 246))
        d.rectangle((wx0, (wy0 + wy1) / 2 - 7 * s, wx1, (wy0 + wy1) / 2 + 7 * s), fill=(246, 246, 246))
        # Shelves with books, and a clock.
        colors = [(70, 110, 170), (200, 90, 80), (240, 190, 90), (90, 150, 120), (150, 110, 170), (60, 70, 90)]
        for row, shelf_y in enumerate((330, 560)):
            x = 1360
            for i in range(9):
                bw, bh = (22 + (i * 7 + row * 5) % 16), (90 + (i * 13 + row * 11) % 50)
                d.rectangle((x * s, (shelf_y - bh) * s, (x + bw) * s, shelf_y * s), fill=colors[(i + row * 2) % len(colors)])
                x += bw + 4
            d.rectangle((1340 * s, shelf_y * s, 1780 * s, (shelf_y + 16) * s), fill=(150, 112, 80))
        d.ellipse((1600 * s, 70 * s, 1720 * s, 190 * s), fill=(250, 250, 250), outline=(90, 90, 100), width=int(8 * s))
        d.line((1660 * s, 130 * s, 1660 * s, 92 * s), fill=(60, 60, 70), width=int(6 * s))
        d.line((1660 * s, 130 * s, 1690 * s, 140 * s), fill=(60, 60, 70), width=int(5 * s))
        # Full-width desk, level with the character's desk.
        top = py + (character.DESK_Y - box_y0) * k
        front = py + (character.DESK_FRONT_Y - box_y0) * k
        d.rectangle((0, top, W, front), fill=character.DESK_TOP)
        d.rectangle((0, front, W, H), fill=character.DESK_FRONT)
        d.rectangle((0, front, W, front + 6 * k), fill=character.DESK_EDGE)
        return (k, px, py), np.asarray(img)[..., ::-1].copy()

    def _build_laptop(self):
        W, H = self.width, self.height
        s = W / 1920  # all measurements below are for 1920x1080
        sw, sh = int(1344 * s), int(756 * s)
        sx, sy = (W - sw) // 2, int(96 * s)
        bezel, lid_r = int(26 * s), int(30 * s)
        lid = (sx - bezel, sy - bezel, sx + sw + bezel, sy + sh + bezel + int(18 * s))
        base_top, base_h = lid[3], int(30 * s)
        base_l, base_r = int(150 * s), W - int(150 * s)

        img = Image.fromarray(self.backdrop[..., ::-1].copy()).convert("RGBA")

        # Soft shadow under the laptop.
        shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(shadow).ellipse((base_l + 40 * s, base_top + base_h - 10 * s,
                                        base_r - 40 * s, base_top + base_h + 40 * s), fill=(0, 0, 0, 110))
        img = Image.alpha_composite(img, shadow.filter(ImageFilter.GaussianBlur(18 * s)))

        d = ImageDraw.Draw(img)
        d.rounded_rectangle(lid, radius=lid_r, fill=(30, 31, 35, 255), outline=(70, 72, 78, 255), width=max(2, int(3 * s)))
        d.ellipse((W / 2 - 5 * s, sy - bezel / 2 - 5 * s, W / 2 + 5 * s, sy - bezel / 2 + 5 * s), fill=(60, 62, 68, 255))
        d.rectangle((sx, sy, sx + sw, sy + sh), fill=(0, 0, 0, 255))
        # Base: a flat trapezoid with a notch for opening the lid.
        d.polygon([(lid[0] - 40 * s, base_top), (lid[2] + 40 * s, base_top),
                   (base_r, base_top + base_h - 8 * s), (base_r - 10 * s, base_top + base_h),
                   (base_l + 10 * s, base_top + base_h), (base_l, base_top + base_h - 8 * s)],
                  fill=(196, 199, 205, 255))
        d.rectangle((base_l, base_top + base_h - 8 * s, base_r, base_top + base_h - 6 * s), fill=(150, 153, 160, 255))
        d.rounded_rectangle((W / 2 - 110 * s, base_top, W / 2 + 110 * s, base_top + 10 * s),
                            radius=int(6 * s), fill=(160, 163, 170, 255))

        laptop = np.asarray(img.convert("RGB"))[..., ::-1].copy()
        return (sx, sy, sw, sh), laptop


class ScreenView:
    """Places a recording frame on the laptop screen, with optional zoom.

    Recording coordinates (as in metadata.json) are mapped to canvas pixels by
    `to_canvas`, which accounts for letterboxing and the current zoom.
    """

    def __init__(self, stage, source_size):
        self.stage = stage
        self.src_w, self.src_h = source_size
        sx, sy, sw, sh = stage.screen
        fit = min(sw / self.src_w, sh / self.src_h)
        self.dw, self.dh = int(self.src_w * fit), int(self.src_h * fit)
        self.dx, self.dy = sx + (sw - self.dw) // 2, sy + (sh - self.dh) // 2
        self.set_zoom(1.0, (self.src_w / 2, self.src_h / 2))

    def set_zoom(self, scale, center):
        """Shows a 1/scale part of the recording centered as close to `center` as fits."""
        cw, ch = self.src_w / scale, self.src_h / scale
        x0 = min(max(center[0] - cw / 2, 0), self.src_w - cw)
        y0 = min(max(center[1] - ch / 2, 0), self.src_h - ch)
        self.crop = (x0, y0, cw, ch)

    def to_canvas(self, x, y):
        x0, y0, cw, ch = self.crop
        return (self.dx + (x - x0) / cw * self.dw, self.dy + (y - y0) / ch * self.dh)

    def visible(self, x, y):
        cx, cy = self.to_canvas(x, y)
        return self.dx <= cx < self.dx + self.dw and self.dy <= cy < self.dy + self.dh

    def draw(self, canvas, frame):
        """Draws `frame` (a recording frame) onto the laptop screen in `canvas`."""
        fh, fw = frame.shape[:2]
        if (fw, fh) != (self.src_w, self.src_h):
            frame = cv2.resize(frame, (self.src_w, self.src_h), interpolation=cv2.INTER_AREA)
        x0, y0, cw, ch = self.crop
        crop = frame[int(y0):int(y0 + ch), int(x0):int(x0 + cw)]
        interp = cv2.INTER_AREA if crop.shape[1] > self.dw else cv2.INTER_LINEAR
        canvas[self.dy:self.dy + self.dh, self.dx:self.dx + self.dw] = cv2.resize(crop, (self.dw, self.dh), interpolation=interp)


def zoom_at(props, t, default_center):
    """(scale, center) at segment time t from the segment's zoom props."""
    for p in props:
        if p["type"] != "zoom" or not p["start"] <= t <= p["start"] + p["duration"]:
            continue
        ramp = min(0.6, p["duration"] / 3)
        local = t - p["start"]
        k = smoothstep(min(local / ramp, (p["duration"] - local) / ramp, 1.0))
        cx = default_center[0] + (p["center"][0] - default_center[0]) * k
        cy = default_center[1] + (p["center"][1] - default_center[1]) * k
        return 1 + (p["scale"] - 1) * k, (cx, cy)
    return 1.0, default_center
