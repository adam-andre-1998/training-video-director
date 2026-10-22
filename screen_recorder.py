"""
Screen recorder that saves an MP4 plus enriched input events.

Every recording made into an output folder is appended to that folder's
metadata.json, together with the clicks and typing that happened during it.
Clicks carry a timestamp (seconds from the start of the video), the matching
frame number and the location in video pixel coordinates. Consecutive key
presses are grouped into one "type" action with start and end timestamps.

One run records a whole video, one take per step: press F9 to start a take
and F9 again to stop it, from any window, so starting and stopping never shows
up in the recording. After each take you can describe it in a few words, or
type "redo" to throw it away. Press Ctrl+C in this window when you're done.

Usage:
    python screen_recorder.py google-slides         # takes go in recordings/google-slides/
    python screen_recorder.py                       # takes go in recordings/
    python screen_recorder.py --now -d 30           # one take, starting now, 30 s long
    python screen_recorder.py -o demos --fps 30 --scale 0.5
"""

import argparse
import ctypes
import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# Make coordinates physical pixels on high-DPI Windows displays, so the mouse
# positions reported by pynput line up with the pixels captured by mss.
# This must run before mss/pynput are imported.
if sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

import cv2
import mss
import numpy as np
from pynput import keyboard, mouse

_mss = getattr(mss, "MSS", None) or mss.mss  # mss.mss is deprecated in newer releases

METADATA_FILE = "metadata.json"
TYPING_GAP = 2.0  # seconds without a key press that ends a "type" action

MODIFIERS = {
    keyboard.Key.ctrl: "ctrl", keyboard.Key.ctrl_l: "ctrl", keyboard.Key.ctrl_r: "ctrl",
    keyboard.Key.alt: "alt", keyboard.Key.alt_l: "alt", keyboard.Key.alt_r: "alt",
    keyboard.Key.alt_gr: "alt",
    keyboard.Key.shift: "shift", keyboard.Key.shift_l: "shift", keyboard.Key.shift_r: "shift",
    keyboard.Key.cmd: "win", keyboard.Key.cmd_l: "win", keyboard.Key.cmd_r: "win",
}
MODIFIER_ORDER = ["ctrl", "alt", "shift", "win"]
# Special keys that are written into typed text as themselves rather than as [name].
KEY_TEXT = {keyboard.Key.space: " ", keyboard.Key.enter: "\n", keyboard.Key.tab: "\t"}


def active_window_title():
    """Title of the foreground window (Windows only), or None."""
    if sys.platform != "win32":
        return None
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value or None
    except Exception:
        return None


class WindowsCursor:
    """Draws the real mouse pointer (arrow, I-beam, hand, ...) onto frames.

    mss screenshots don't include the pointer, so each cursor shape is rendered
    once with GDI, over black and over white to recover its transparency, and
    then blended onto every frame at the current pointer position.
    """
    SIZE = 256  # canvas big enough for large / high-DPI cursors
    CURSOR_SHOWING = 0x1
    DI_NORMAL = 0x3
    BLACKNESS = 0x00000042
    WHITENESS = 0x00FF0062

    def __init__(self, monitor, scale):
        from ctypes import wintypes as wt

        class CURSORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wt.DWORD), ("flags", wt.DWORD),
                        ("hCursor", wt.HANDLE), ("ptScreenPos", wt.POINT)]

        class ICONINFO(ctypes.Structure):
            _fields_ = [("fIcon", wt.BOOL), ("xHotspot", wt.DWORD), ("yHotspot", wt.DWORD),
                        ("hbmMask", wt.HBITMAP), ("hbmColor", wt.HBITMAP)]

        self.CURSORINFO, self.ICONINFO = CURSORINFO, ICONINFO
        # Private DLL handles so our argtypes don't clash with pynput's.
        u = self.user32 = ctypes.WinDLL("user32")
        g = self.gdi32 = ctypes.WinDLL("gdi32")
        u.GetCursorInfo.argtypes = [ctypes.POINTER(CURSORINFO)]
        u.GetIconInfo.argtypes = [wt.HANDLE, ctypes.POINTER(ICONINFO)]
        u.GetDC.argtypes, u.GetDC.restype = [wt.HWND], wt.HDC
        u.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
        u.DrawIconEx.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, wt.HANDLE, ctypes.c_int,
                                 ctypes.c_int, wt.UINT, wt.HBRUSH, wt.UINT]
        g.CreateCompatibleDC.argtypes, g.CreateCompatibleDC.restype = [wt.HDC], wt.HDC
        g.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
        g.CreateCompatibleBitmap.restype = wt.HBITMAP
        g.SelectObject.argtypes, g.SelectObject.restype = [wt.HDC, wt.HGDIOBJ], wt.HGDIOBJ
        g.PatBlt.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.DWORD]
        g.GetBitmapBits.argtypes = [wt.HBITMAP, wt.LONG, ctypes.c_void_p]
        g.DeleteObject.argtypes = [wt.HGDIOBJ]
        g.DeleteDC.argtypes = [wt.HDC]

        self.monitor = monitor
        self.scale = scale
        self._cache = {}

    def _render(self, hcursor):
        """Returns (premultiplied BGR, alpha, invert mask, hotspot) for a cursor, scaled."""
        u, g, S = self.user32, self.gdi32, self.SIZE
        info = self.ICONINFO()
        if not u.GetIconInfo(hcursor, ctypes.byref(info)):
            return None
        hotspot = (info.xHotspot, info.yHotspot)
        for bmp in (info.hbmMask, info.hbmColor):
            if bmp:
                g.DeleteObject(bmp)

        screen_dc = u.GetDC(None)
        mem_dc = g.CreateCompatibleDC(screen_dc)
        bmp = g.CreateCompatibleBitmap(screen_dc, S, S)
        old = g.SelectObject(mem_dc, bmp)
        buf = (ctypes.c_ubyte * (S * S * 4))()
        shots = []
        try:
            for background in (self.BLACKNESS, self.WHITENESS):
                g.PatBlt(mem_dc, 0, 0, S, S, background)
                u.DrawIconEx(mem_dc, 0, 0, hcursor, 0, 0, 0, None, self.DI_NORMAL)
                g.GetBitmapBits(bmp, S * S * 4, buf)
                shots.append(np.frombuffer(buf, np.uint8).reshape(S, S, 4)[:, :, :3].astype(np.float32))
        finally:
            g.SelectObject(mem_dc, old)
            g.DeleteObject(bmp)
            g.DeleteDC(mem_dc)
            u.ReleaseDC(None, screen_dc)

        black, white = shots
        # diff: 255 = transparent, 0 = opaque, negative = "inverts what's below" (e.g. I-beam)
        diff = (white - black).mean(axis=2)
        invert = diff < -128
        alpha = np.clip(1 - diff / 255, 0, 1)
        alpha[invert] = 0
        premult = black * alpha[..., None]

        ys, xs = np.nonzero((alpha > 0) | invert)
        if not len(ys):
            return None
        h, w = ys.max() + 1, xs.max() + 1
        premult, alpha, invert = premult[:h, :w], alpha[:h, :w], invert[:h, :w]

        if self.scale != 1:
            size = (max(1, round(w * self.scale)), max(1, round(h * self.scale)))
            premult = cv2.resize(premult, size, interpolation=cv2.INTER_AREA)
            alpha = cv2.resize(alpha, size, interpolation=cv2.INTER_AREA)
            invert = cv2.resize(invert.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST).astype(bool)
            hotspot = (hotspot[0] * self.scale, hotspot[1] * self.scale)
        return premult, alpha, invert, hotspot

    def draw(self, frame):
        info = self.CURSORINFO(cbSize=ctypes.sizeof(self.CURSORINFO))
        if not self.user32.GetCursorInfo(ctypes.byref(info)) or not info.flags & self.CURSOR_SHOWING:
            return
        if info.hCursor not in self._cache:
            self._cache[info.hCursor] = self._render(info.hCursor)
        cursor = self._cache[info.hCursor]
        if cursor is None:
            return
        premult, alpha, invert, (hx, hy) = cursor

        x = round((info.ptScreenPos.x - self.monitor["left"]) * self.scale - hx)
        y = round((info.ptScreenPos.y - self.monitor["top"]) * self.scale - hy)
        h, w = alpha.shape
        fh, fw = frame.shape[:2]
        x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, fw), min(y + h, fh)
        if x0 >= x1 or y0 >= y1:
            return
        cs = (slice(y0 - y, y1 - y), slice(x0 - x, x1 - x))
        region = frame[y0:y1, x0:x1].astype(np.float32)
        region = region * (1 - alpha[cs][..., None]) + premult[cs]
        region[invert[cs]] = 255 - region[invert[cs]]
        frame[y0:y1, x0:x1] = np.clip(region, 0, 255).astype(np.uint8)


class ScreenRecorder:
    def __init__(self, output_dir, monitor=1, fps=15, scale=1.0, description="",
                 record_keys=True, draw_cursor=True, stop_key="f9",
                 typing_gap=TYPING_GAP):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.fps = fps
        self.scale = scale
        self.description = description
        self.record_keys = record_keys
        self.typing_gap = typing_gap
        self.draw_cursor = draw_cursor
        self.stop_key = getattr(keyboard.Key, stop_key.lower(), None)

        with _mss() as sct:
            if monitor >= len(sct.monitors):
                raise ValueError(f"Monitor {monitor} not found; available: 0-{len(sct.monitors) - 1}")
            self.monitor = dict(sct.monitors[monitor])

        # Video dimensions (even numbers keep codecs happy).
        self.width = int(self.monitor["width"] * scale) // 2 * 2
        self.height = int(self.monitor["height"] * scale) // 2 * 2

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.video_path = self.output_dir / f"recording_{stamp}.mp4"
        n = 1
        while self.video_path.exists():
            self.video_path = self.output_dir / f"recording_{stamp}_{n}.mp4"
            n += 1

        self.start_event = threading.Event()
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.events = []
        self.frames_written = 0
        self.start_time = None
        self.started_at = None

        self.cursor = mouse.Controller().position
        self.cursor_renderer = None
        if draw_cursor and sys.platform == "win32":
            try:
                self.cursor_renderer = WindowsCursor(self.monitor, scale)
            except Exception as exc:
                print(f"Real cursor unavailable ({exc}); drawing a marker instead")
        self._held_modifiers = set()
        self._typing = None  # in-progress "type" action

    # ------------------------------------------------------------------ helpers
    def _now(self):
        return time.perf_counter() - self.start_time

    def _to_video(self, x, y):
        """Screen coordinates -> video pixel coordinates, or None if off-screen."""
        vx = (x - self.monitor["left"]) * self.scale
        vy = (y - self.monitor["top"]) * self.scale
        if 0 <= vx < self.width and 0 <= vy < self.height:
            return [int(vx), int(vy)]
        return None

    def _add(self, action, t, **fields):
        event = {"action": action, "timestamp": round(t, 3), "frame": int(t * self.fps)}
        event.update({k: v for k, v in fields.items() if v is not None})
        self.events.append(event)
        return event

    def _flush_typing(self):
        """Close the in-progress "type" action and store it."""
        typing, self._typing = self._typing, None
        if typing and typing["_tokens"]:
            window = typing.pop("window")
            typing["text"] = "".join(typing.pop("_tokens"))
            if window:
                typing["window"] = window
            self.events.append(typing)

    # ------------------------------------------------------------ mouse events
    def on_move(self, x, y):
        self.cursor = (x, y)

    def on_click(self, x, y, button, pressed):
        if not pressed or self.start_time is None:
            return
        loc = self._to_video(x, y)
        if not loc:
            return
        t = self._now()
        with self.lock:
            self._flush_typing()
            self._add("click", t, location=loc, button=button.name, window=active_window_title())

    # --------------------------------------------------------- keyboard events
    def on_press(self, key):
        if key == self.stop_key:
            # The same key starts a take that's waiting for it, and stops a running one
            # (but not in the first half second, when it may just be the start key repeating).
            if not self.start_event.is_set():
                self.start_event.set()
            elif self.start_time is None or self._now() > 0.5:
                self.stop_event.set()
            return
        if self.start_time is None or not self.record_keys:
            return
        t = self._now()
        with self.lock:
            if key in MODIFIERS:
                self._held_modifiers.add(MODIFIERS[key])
                return

            if self._typing and t - self._typing["end_timestamp"] > self.typing_gap:
                self._flush_typing()
            if not self._typing:
                self._typing = {"action": "type",
                                "start_timestamp": round(t, 3), "end_timestamp": round(t, 3),
                                "start_frame": int(t * self.fps), "end_frame": int(t * self.fps),
                                "_tokens": [], "window": active_window_title()}
            typing = self._typing
            typing["end_timestamp"] = round(t, 3)
            typing["end_frame"] = int(t * self.fps)

            # Each token is one typed character, or a special key / shortcut
            # written as "[name]", e.g. "[ctrl+s]" or "[left]".
            mods = [m for m in MODIFIER_ORDER if m in self._held_modifiers]
            is_shortcut = any(m in mods for m in ("ctrl", "alt", "win"))
            char = KEY_TEXT.get(key, getattr(key, "char", None))
            tokens = typing["_tokens"]
            if char and (char.isprintable() or char in "\n\t") and not is_shortcut:
                tokens.append(char)
            elif key == keyboard.Key.backspace and not mods and tokens and len(tokens[-1]) == 1:
                tokens.pop()
            else:
                tokens.append("[" + "+".join(mods + [self._key_name(key)]) + "]")

    def on_release(self, key):
        if key in MODIFIERS:
            with self.lock:
                self._held_modifiers.discard(MODIFIERS[key])

    @staticmethod
    def _key_name(key):
        if isinstance(key, keyboard.Key):
            return key.name
        vk = getattr(key, "vk", None)
        # With Ctrl held, key.char is a control character; use the virtual key instead.
        if vk is not None and (0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A):
            return chr(vk).lower()
        if key.char and key.char.isprintable():
            return key.char
        return f"vk{vk}" if vk is not None else "unknown"

    # ------------------------------------------------------------------ capture
    def _capture_loop(self):
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(self.video_path), fourcc, self.fps, (self.width, self.height))
        if not writer.isOpened():
            self.capture_error = RuntimeError("Could not open video writer")
            self.stop_event.set()
            return
        try:
            with _mss() as sct:
                while not self.stop_event.is_set():
                    frame = cv2.cvtColor(np.asarray(sct.grab(self.monitor)), cv2.COLOR_BGRA2BGR)
                    if frame.shape[1] != self.width or frame.shape[0] != self.height:
                        frame = cv2.resize(frame, (self.width, self.height), interpolation=cv2.INTER_AREA)
                    if self.cursor_renderer:
                        try:
                            self.cursor_renderer.draw(frame)
                        except Exception as exc:
                            print(f"Real cursor failed ({exc}); drawing a marker instead")
                            self.cursor_renderer = None
                    elif self.draw_cursor:
                        pos = self._to_video(*self.cursor)
                        if pos:
                            r = max(4, int(8 * self.scale))
                            cv2.circle(frame, tuple(pos), r, (0, 0, 255), 2, cv2.LINE_AA)

                    # Keep video time in step with wall-clock time: if a grab ran
                    # slow, repeat the frame so event timestamps stay aligned.
                    target = int(self._now() * self.fps) + 1
                    while self.frames_written < target:
                        writer.write(frame)
                        self.frames_written += 1

                    delay = self.frames_written / self.fps - self._now()
                    if delay > 0:
                        self.stop_event.wait(delay)
        except Exception as exc:
            self.capture_error = exc
            self.stop_event.set()
        finally:
            writer.release()

    # --------------------------------------------------------------- lifecycle
    def record(self, duration=None, wait_for_start=False):
        """Records one take. Returns True if anything was recorded.

        With wait_for_start, capture begins when the stop key is pressed (in
        any window), so the take starts on the screen the user has set up and
        the recorder's own window never appears in it. Ctrl+C before that
        returns False without recording.
        """
        self.capture_error = None
        if wait_for_start and not self.stop_key:
            raise ValueError("Unknown --stop-key; it's also the key that starts a take")
        mouse_listener = mouse.Listener(on_move=self.on_move, on_click=self.on_click)
        key_listener = keyboard.Listener(on_press=self.on_press, on_release=self.on_release)
        mouse_listener.start()
        key_listener.start()
        try:
            if wait_for_start:
                try:
                    while not self.start_event.wait(0.1):
                        pass
                except KeyboardInterrupt:
                    return False
            self.start_event.set()
            self._capture(duration)
        finally:
            mouse_listener.stop()
            key_listener.stop()

        if self.capture_error:
            raise self.capture_error
        return self.frames_written > 0

    def _capture(self, duration):
        self.started_at = datetime.now().astimezone()
        self.start_time = time.perf_counter()
        capture = threading.Thread(target=self._capture_loop, daemon=True)
        capture.start()

        stop_hint = f"press {self.stop_key.name.upper()} or " if self.stop_key else ""
        print(f"Recording monitor {self.monitor['width']}x{self.monitor['height']} "
              f"-> {self.video_path.name} ({self.width}x{self.height} @ {self.fps} fps)")
        print(f"To stop, {stop_hint}Ctrl+C here" + (f" (auto-stops after {duration}s)" if duration else ""))
        try:
            while not self.stop_event.is_set():
                if duration and self._now() >= duration:
                    break
                self.stop_event.wait(0.1)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop_event.set()
            capture.join()

    def discard(self):
        """Deletes the take's video without adding it to metadata.json."""
        self.video_path.unlink(missing_ok=True)
        print(f"Discarded {self.video_path.name}")

    def save(self, description=None):
        """Appends the take and its events to the folder's metadata.json."""
        if description is not None:
            self.description = description
        with self.lock:
            self._flush_typing()
            events = sorted(self.events, key=lambda e: e.get("timestamp", e.get("start_timestamp")))
        duration = round(self.frames_written / self.fps, 3)
        cleaned = []
        in_video = (e for e in events if e.get("timestamp", e.get("start_timestamp")) <= duration)
        for i, ev in enumerate(in_video):
            ev = {k: v for k, v in ev.items() if not k.startswith("_")}
            cleaned.append({"id": i + 1, **ev})

        meta_path = self.output_dir / METADATA_FILE
        data = load_metadata(self.output_dir)

        recording = {
            "id": max((r.get("id", 0) for r in data["recordings"]), default=0) + 1,
            "file_name": self.video_path.name,
            "duration": duration,
            "description": self.description,
            "created_at": self.started_at.isoformat(timespec="seconds"),
            "resolution": [self.width, self.height],
            "fps": self.fps,
            "screen": {k: self.monitor[k] for k in ("left", "top", "width", "height")},
            "scale": self.scale,
            "events": cleaned,
        }
        data["recordings"].append(recording)

        # Write to a temp file then swap, so a crash never leaves half a JSON file.
        tmp = meta_path.with_suffix(".json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        os.replace(tmp, meta_path)

        print(f"Saved {self.video_path} ({duration}s, {len(cleaned)} events)")
        print(f"Appended recording #{recording['id']} to {meta_path}")
        return recording


def load_metadata(folder):
    meta_path = Path(folder) / METADATA_FILE
    data = {"recordings": []}
    if meta_path.exists():
        with open(meta_path, encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("recordings", [])
    return data


def ask(prompt):
    """input() that treats a closed stdin or Ctrl+C as an empty answer."""
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""


def record_session(make_recorder, args):
    """Records takes until Ctrl+C. The hotkey starts and stops each one; then it's described or redone."""
    key = args.stop_key.upper()
    saved = []
    while True:
        recorder = make_recorder()
        print(f"\nTake {len(saved) + 1}: set up the screen, then press {key} to start recording."
              + ("  Press Ctrl+C here when you're done." if saved else ""))
        if not recorder.record(duration=args.duration, wait_for_start=True):
            break
        if args.description:
            saved.append(recorder.save())
            continue
        answer = ask('What does this take show? (a few words; Enter to skip, "redo" to throw it away): ')
        if answer.lower() in ("redo", "r"):
            recorder.discard()
            continue
        saved.append(recorder.save(answer))
    return saved


def main():
    p = argparse.ArgumentParser(description="Record the screen to MP4 with click/typing metadata.")
    p.add_argument("name", nargs="?", help="video name: takes go in recordings/<name>/ (default: recordings/)")
    p.add_argument("-o", "--output", help="output folder, instead of one named after the video")
    p.add_argument("-d", "--duration", type=float, help="stop each take automatically after N seconds")
    p.add_argument("--now", action="store_true",
                   help="record a single take, starting immediately, with no questions")
    p.add_argument("--fps", type=int, default=15, help="frames per second (default: 15)")
    p.add_argument("--monitor", type=int, default=1, help="1 = primary, 2 = second..., 0 = all monitors")
    p.add_argument("--scale", type=float, default=1.0, help="resize video, e.g. 0.5 for half size")
    p.add_argument("--description", default="",
                   help="description stored with every take (skips the question after each take)")
    p.add_argument("--stop-key", default="f9", help="global key that starts and stops takes (default: f9)")
    p.add_argument("--no-keys", action="store_true", help="don't log keyboard input")
    p.add_argument("--typing-gap", type=float, default=TYPING_GAP,
                   help=f"seconds without a key press that ends a typing action (default: {TYPING_GAP})")
    p.add_argument("--no-cursor", action="store_true", help="don't draw the cursor marker into the video")
    args = p.parse_args()

    output = Path(args.output) if args.output else Path("recordings") / (args.name or "")
    existing = load_metadata(output)["recordings"]
    if existing:
        print(f"{output} already has {len(existing)} recording(s); new takes are added after them.")
        if not (args.name or args.output):
            print("To start a separate video instead, give it a name:  python screen_recorder.py <video-name>")

    def make_recorder():
        return ScreenRecorder(
            output_dir=output, monitor=args.monitor, fps=args.fps, scale=args.scale,
            description=args.description, record_keys=not args.no_keys,
            draw_cursor=not args.no_cursor, stop_key=args.stop_key, typing_gap=args.typing_gap,
        )

    if args.now:
        recorder = make_recorder()
        saved = [recorder.save()] if recorder.record(duration=args.duration) else []
    else:
        saved = record_session(make_recorder, args)

    if not saved:
        print("\nNothing recorded.")
        return
    print(f"\nRecorded {len(saved)} take(s); {output} has {len(existing) + len(saved)} recording(s) in all.")
    print(f"Next, ask Claude Code:  make a training video from {(output / METADATA_FILE).resolve()}")


if __name__ == "__main__":
    main()
