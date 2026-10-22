"""Rendering the timeline frame by frame."""

import cv2
import numpy as np

from . import character
from .audio import activity
from .config import ACCENT, FADE, WHITE
from .draw import blit, blit_masked, blit_premult, ease_out, fade, text_box
from .layout import ScreenView, Stage, zoom_at
from .media import ClipReader
from .props import PropContext, draw_props


class Renderer:
    """Renders the timeline frame by frame.

    loudness: narration loudness per output frame (0..1), used for lip sync.
    """

    def __init__(self, timeline, width, height, fps, loudness=None):
        self.timeline = timeline
        self.width, self.height, self.fps = width, height, fps
        self.s = width / 1920
        self.stage = Stage(width, height)
        self.character = character.Character()
        total = int(round(timeline.duration * fps))
        self.loudness = loudness if loudness is not None else np.zeros(total, np.float32)
        self.activity = activity(self.loudness, fps)
        self._readers = {}   # video path -> ClipReader
        self._views = {}     # segment id -> ScreenView
        self._stills = {}    # segment id -> frame

    # ---------------------------------------------------------------- main loop
    def frames(self, first=0, last=None):
        """Yields output frames first..last-1 (default: all of them), BGR, in order.

        Every frame depends only on its own time, so separate processes can
        render separate ranges of the same timeline.
        """
        segments = self.timeline.segments
        total = int(round(self.timeline.duration * self.fps))
        i_seg = 0
        for i in range(first, total if last is None else min(last, total)):
            T = i / self.fps
            while i_seg < len(segments) - 1 and T >= segments[i_seg].end:
                i_seg += 1
            seg = segments[i_seg]
            frame = self.render_segment(seg, T - seg.start, i)
            # Fade in from black at the start and out at the end.
            k = min(T / FADE, (self.timeline.duration - T) / FADE, 1.0)
            if k < 1:
                frame = (frame * max(k, 0)).astype(np.uint8)
            yield frame
        for reader in self._readers.values():
            reader.close()

    def render_segment(self, seg, t, index):
        if seg.type == "title_card":
            return self.title_card(seg, t)
        if seg.type in ("cartoon_talking", "cartoon_silent"):
            return self.cartoon(seg, t, index)
        return self.screen(seg, t, index)

    def presenter_frame(self, index, talking):
        """The character for output frame `index`: (premultiplied BGR, alpha) for character.BOX."""
        level = act = 0.0
        if talking and index < len(self.loudness):
            level, act = float(self.loudness[index]), float(self.activity[index])
        return self.character.frame(index / self.fps, level, act)

    # ------------------------------------------------------------ segment types
    def title_card(self, seg, t):
        canvas = self.stage.backdrop.copy()
        s = self.s
        title = text_box(seg.text.get("title", self.timeline.title), int(84 * s), WHITE, kind="bold")
        rise = (1 - ease_out(t / 0.6)) * 30 * s
        y = self.height * 0.40 - title.shape[0] / 2
        blit(canvas, title, (self.width - title.shape[1]) / 2, y + rise, fade(t, seg.duration, 0.5, 0.4))

        line_w = int(min(title.shape[1], 420 * s) * ease_out((t - 0.3) / 0.6))
        if line_w > 0:
            ly = int(y + title.shape[0] + 24 * s)
            cv2.rectangle(canvas, ((self.width - line_w) // 2, ly), ((self.width + line_w) // 2, ly + int(8 * s)), ACCENT, -1)

        if seg.text.get("subtitle"):
            sub = text_box(seg.text["subtitle"], int(44 * s), (235, 225, 215))
            blit(canvas, sub, (self.width - sub.shape[1]) / 2, y + title.shape[0] + 60 * s + rise,
                 fade(t - 0.4, seg.duration - 0.4, 0.5, 0.4))
        self.props(canvas, seg, t)
        return canvas

    def cartoon(self, seg, t, index):
        canvas = self.stage.office.copy()
        bgr, alpha = self.presenter_frame(index, seg.type == "cartoon_talking")
        k, x, y = self.stage.presenter
        size = (int(round(alpha.shape[1] * k)), int(round(alpha.shape[0] * k)))
        blit_premult(canvas, cv2.resize(bgr, size), cv2.resize(alpha, size), x, y)
        self.props(canvas, seg, t)
        return canvas

    def screen(self, seg, t, index):
        canvas = self.stage.laptop.copy()
        view = self._views.get(seg.id)
        if view is None:
            view = self._views[seg.id] = ScreenView(self.stage, tuple(seg.recording["resolution"]))
        center = (view.src_w / 2, view.src_h / 2)
        view.set_zoom(*zoom_at(seg.props, t, center))
        view.draw(canvas, self.recording_frame(seg, t))
        self.props(canvas, seg, t, view)
        if seg.presenter in ("talking", "silent"):
            self.picture_in_picture(canvas, index, seg.presenter == "talking")
        return canvas

    def recording_frame(self, seg, t):
        path = self.timeline.recordings_dir / seg.source["file_name"]
        reader = self._readers.get(path)
        if reader is None:
            reader = self._readers[path] = ClipReader(path)
        if seg.type == "screen_still":
            if seg.id not in self._stills:
                self._stills[seg.id] = reader.frame_at(seg.source["time"]).copy()
            return self._stills[seg.id]
        # Past the planned clip length (narration ran long) the last frame is held.
        t = min(t, seg.clip_duration)
        return reader.frame_at(seg.source["clip_start"] + t * seg.source.get("speed", 1.0))

    # ----------------------------------------------------------------- overlays
    def props(self, canvas, seg, t, view=None):
        if not seg.props:
            return
        events = {e["id"]: e for e in seg.recording.get("events", [])} if seg.recording else {}
        ctx = PropContext(self.width, self.height, self.s, view=view, segment=seg, events=events)
        draw_props(canvas, seg.props, t, ctx)

    def picture_in_picture(self, canvas, index, talking):
        """The presenter in a circle in the bottom-right corner."""
        s = self.s
        r = int(150 * s)
        size = 2 * r
        tile = np.empty((size, size, 3), np.uint8)
        tile[:] = (226, 216, 206)
        bgr, alpha = self.presenter_frame(index, talking)
        x0, y0, x1, y1 = character.PORTRAIT
        bx, by = character.BOX[:2]
        crop = (slice(y0 - by, y1 - by), slice(x0 - bx, x1 - bx))
        blit_premult(tile, cv2.resize(bgr[crop], (size, size), interpolation=cv2.INTER_AREA),
                     cv2.resize(alpha[crop], (size, size), interpolation=cv2.INTER_AREA), 0, 0)

        mask = np.zeros((size, size), np.uint8)
        cv2.circle(mask, (r, r), r - 1, 255, -1, cv2.LINE_AA)
        cx, cy = self.width - r - int(40 * s), self.height - r - int(40 * s)
        cv2.circle(canvas, (cx, cy), r + int(7 * s), WHITE, -1, cv2.LINE_AA)
        blit_masked(canvas, tile, mask.astype(np.float32) / 255, cx - r, cy - r)
