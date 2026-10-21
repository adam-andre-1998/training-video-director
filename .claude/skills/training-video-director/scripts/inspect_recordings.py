"""
Summarize screen recordings for the training video director.

Prints every recording in a metadata.json with its events in time order,
including idle gaps, and saves a small set of key screenshots so the director
can see what was clicked without spending many tokens on images:

- Repeated clicks on the same spot (double and triple clicks) share one screenshot.
- Clicks and shortcuts in a different window at the very start or end of a
  recording (starting and stopping the recorder) get none.
- Typing gets none: the typed text is in the event log.
- A full "overview" screenshot is saved only when the screen has changed a lot
  since the last overview (a new page or dialog). Other clicks get a small
  "detail" crop around the click, which costs about a quarter as much.
- One "end" screenshot shows the final result, if the screen changed.
- At most --max-images screenshots in total (overviews first).

Usage:
    python inspect_recordings.py path/to/metadata.json
    python inspect_recordings.py path/to/metadata.json --max-images 8
    python inspect_recordings.py path/to/metadata.json --no-frames   # event log only
    python inspect_recordings.py path/to/metadata.json --clean       # delete the screenshots

Screenshots need opencv-python (in the project's requirements.txt). The event
log uses only the standard library.
"""

import argparse
import json
import math
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

GAP_NOTE = 3.0            # report idle gaps longer than this many seconds
REPEAT_DISTANCE = 30      # clicks this close (px) ...
REPEAT_SECONDS = 1.5      # ... and this close in time count as one moment
EDGE_SECONDS = 2.5        # off-window events this near the start/end are recorder control
SCENE_CHANGE = 0.08       # mean pixel difference (0..1) that counts as a new screen
OVERVIEW_WIDTH = 1024     # overview screenshots are scaled to this width
DETAIL_SIZE = (0.34, 0.38)  # detail crop size as a fraction of the recording's width and height
INSET_SIZE = (240, 160)   # area around a click shown enlarged in an overview's corner
INSET_ZOOM = 2
DEFAULT_MAX_IMAGES = 12


def event_time(ev):
    return ev.get("timestamp", ev.get("start_timestamp", 0.0))


def describe(ev):
    window = f"  [{ev['window']}]" if ev.get("window") else ""
    if ev["action"] == "click":
        x, y = ev["location"]
        return f"{ev['timestamp']:.2f}s".ljust(15) + f"click {ev.get('button', 'left')} at ({x}, {y}){window}"
    if ev["action"] == "type":
        span = f"{ev['start_timestamp']:.2f}-{ev['end_timestamp']:.2f}s".ljust(15)
        return f"{span}type {json.dumps(ev['text'], ensure_ascii=False)}{window}"
    return f"{event_time(ev):.2f}s".ljust(15) + f"{ev['action']}{window}"


def print_recording(rec, notes):
    w, h = rec.get("resolution", ["?", "?"])
    print(f"\n=== Recording {rec['id']}: {rec['file_name']}")
    print(f"    duration {rec['duration']}s, {w}x{h} @ {rec.get('fps', '?')} fps, "
          f"created {rec.get('created_at', '?')}")
    if rec.get("description"):
        print(f"    description: {rec['description']}")
    events = sorted(rec.get("events", []), key=event_time)
    if not events:
        print("    (no events)")
        return
    print(f"    {'id':>3}  {'time':<15}event")
    prev_end = 0.0
    for ev in events:
        gap = event_time(ev) - prev_end
        if gap > GAP_NOTE:
            print(f"         ... idle {gap:.1f}s ...")
        note = f"   <- {notes[ev['id']]}" if ev["id"] in notes else ""
        print(f"    {ev['id']:>3}  {describe(ev)}{note}")
        prev_end = ev.get("end_timestamp", ev.get("timestamp", prev_end))
    tail = rec["duration"] - prev_end
    if tail > GAP_NOTE:
        print(f"         ... idle {tail:.1f}s until the end ...")


# ---------------------------------------------------------- key moments
@dataclass
class Moment:
    rec: dict
    t: float
    event_ids: list
    location: tuple = None     # None for the end-of-recording moment
    kind: str = ""             # "overview" or "detail", decided from the frames
    frame: object = None
    path: Path = None
    tokens: int = 0
    extra: dict = field(default_factory=dict)

    @property
    def label(self):
        if self.location is None:
            return f"recording {self.rec['id']} end ({self.t:.2f}s)"
        ids = ",".join(str(i) for i in self.event_ids)
        return f"rec {self.rec['id']} event {ids} click @ {self.t:.2f}s {self.location}"


def key_moments(rec):
    """The clicks worth a screenshot, and notes on why other events have none."""
    events = sorted(rec.get("events", []), key=event_time)
    windows = Counter(ev.get("window") for ev in events if ev.get("window"))
    main_window = windows.most_common(1)[0][0] if windows else None
    moments, notes = [], {}
    for ev in events:
        t = event_time(ev)
        near_edge = t < EDGE_SECONDS or t > rec["duration"] - EDGE_SECONDS
        if near_edge and main_window and ev.get("window") and ev["window"] != main_window:
            notes[ev["id"]] = "no screenshot: likely starting/stopping the recorder"
            continue
        if ev["action"] != "click":
            notes[ev["id"]] = "no screenshot: typing (text is shown here)"
            continue
        last = moments[-1] if moments else None
        if (last and t - last.extra["last_t"] <= REPEAT_SECONDS
                and math.dist(last.location, ev["location"]) <= REPEAT_DISTANCE):
            last.event_ids.append(ev["id"])
            last.extra["last_t"] = t
            notes[ev["id"]] = f"repeat click: shares the screenshot of event {last.event_ids[0]}"
            continue
        moments.append(Moment(rec, ev["timestamp"], [ev["id"]], tuple(ev["location"]), extra={"last_t": t}))
    moments.append(Moment(rec, max(rec["duration"] - 0.1, 0), []))
    return moments, notes


# ---------------------------------------------------------------- frames
def grab(cap, fps, t):
    import cv2
    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(t * fps)))
    ok, frame = cap.read()
    return frame if ok else None


def thumb(frame):
    import cv2
    return cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (160, 90), interpolation=cv2.INTER_AREA)


def difference(a, b):
    import numpy as np
    return float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean()) / 255


def classify(moments, video_path):
    """Grabs each moment's frame and marks it overview (new screen) or detail; drops an unchanged end."""
    import cv2
    if not video_path.exists():
        print(f"    (screenshots skipped: {video_path} not found)")
        return []
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 15
    kept, last_overview, last_any = [], None, None
    for m in moments:
        # Clicks: just before the click, so the frame shows what was about to be clicked.
        frame = grab(cap, fps, m.t - 0.05 if m.location else m.t)
        if frame is None:
            continue
        th = thumb(frame)
        if m.location is None and last_any is not None and difference(th, last_any) < SCENE_CHANGE / 2:
            continue  # the end looks like the last screenshot
        if last_overview is None or difference(th, last_overview) > SCENE_CHANGE or m.location is None:
            m.kind, last_overview = "overview", th
        else:
            m.kind = "detail"
        m.frame, last_any = frame, th
        kept.append(m)
    cap.release()
    return kept


def within_budget(moments, max_images):
    """Keeps each recording's first overview, then the other overviews, then details, spreading
    each group evenly when it doesn't all fit."""
    if len(moments) <= max_images:
        return moments, []

    def spread(items, n):
        if n <= 0:
            return []
        if len(items) <= n:
            return items
        step = len(items) / n
        return [items[int(i * step)] for i in range(n)]

    firsts, seen = [], set()
    for m in moments:
        if m.kind == "overview" and m.rec["id"] not in seen:
            firsts.append(m)
            seen.add(m.rec["id"])
    overviews = [m for m in moments if m.kind == "overview" and m not in firsts]
    details = [m for m in moments if m.kind == "detail"]
    chosen = spread(firsts, max_images)
    chosen += spread(overviews, max_images - len(chosen))
    chosen += spread(details, max_images - len(chosen))
    chosen_ids = {id(m) for m in chosen}
    return [m for m in moments if id(m) in chosen_ids], [m for m in moments if id(m) not in chosen_ids]


def label_bar(frame, text, scale=0.7):
    import cv2
    h = int(34 * scale / 0.7)
    cv2.rectangle(frame, (0, 0), (frame.shape[1], h), (0, 0, 0), -1)
    cv2.putText(frame, text, (10, int(h * 0.7)), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 2, cv2.LINE_AA)


def crosshair(frame, x, y, r=22):
    import cv2
    cv2.circle(frame, (x, y), r, (0, 0, 255), 2, cv2.LINE_AA)
    cv2.circle(frame, (x, y), 4, (0, 0, 255), -1, cv2.LINE_AA)
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        cv2.line(frame, (x + (r + 2) * dx, y + (r + 2) * dy), (x + (r + 12) * dx, y + (r + 12) * dy), (0, 0, 255), 2)


def render(m, out_dir, index):
    """Writes the moment's screenshot and returns its estimated token cost."""
    import cv2
    frame = m.frame.copy()
    h, w = frame.shape[:2]
    ids = "-".join(f"e{i:02d}" for i in m.event_ids) or "end"
    if m.kind == "detail":
        cw, ch = int(w * DETAIL_SIZE[0]), int(h * DETAIL_SIZE[1])
        x, y = m.location
        x0 = min(max(x - cw // 2, 0), max(w - cw, 0))
        y0 = min(max(y - ch // 2, 0), max(h - ch, 0))
        out = frame[y0:y0 + ch, x0:x0 + cw].copy()
        crosshair(out, x - x0, y - y0, 16)
        label_bar(out, m.label, 0.5)
    else:
        if m.location:
            x, y = m.location
            iw, ih = INSET_SIZE
            ix = min(max(x - iw // 2, 0), max(w - iw, 0))
            iy = min(max(y - ih // 2, 0), max(h - ih, 0))
            inset = frame[iy:iy + ih, ix:ix + iw].copy()
            crosshair(inset, x - ix, y - iy, 12)
            crosshair(frame, x, y)
        scale = OVERVIEW_WIDTH / w
        out = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else frame
        if m.location:
            inset = cv2.resize(inset, None, fx=INSET_ZOOM * min(scale, 1) * 1.5, fy=INSET_ZOOM * min(scale, 1) * 1.5,
                               interpolation=cv2.INTER_CUBIC)
            oh, ow = out.shape[:2]
            ih2, iw2 = inset.shape[:2]
            if ih2 + 40 < oh and iw2 + 10 < ow:
                px = 10 if x * scale > ow / 2 else ow - iw2 - 10
                py = 40 if y * scale > oh / 2 else oh - ih2 - 10
                out[py:py + ih2, px:px + iw2] = inset
                cv2.rectangle(out, (px, py), (px + iw2, py + ih2), (0, 0, 255), 2)
        label_bar(out, m.label, 0.6)
    m.path = out_dir / f"rec{m.rec['id']}_{index:02d}_{m.kind}_{ids}.png"
    cv2.imwrite(str(m.path), out)
    # Rough image cost for vision models: about one token per 750 pixels.
    return math.ceil(out.shape[0] * out.shape[1] / 750)


def clean(out_dir):
    """Deletes this script's screenshots, and the folder too if nothing else is in it."""
    if not out_dir.is_dir():
        return 0
    removed = 0
    for old in out_dir.glob("rec*.png"):
        old.unlink()
        removed += 1
    if not any(out_dir.iterdir()):
        out_dir.rmdir()
    return removed


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("metadata", help="path to metadata.json")
    p.add_argument("--recording", type=int, action="append", help="only this recording id (repeatable)")
    p.add_argument("--out", help="folder for screenshots (default: <recordings folder>/director_frames)")
    p.add_argument("--max-images", type=int, default=DEFAULT_MAX_IMAGES,
                   help=f"most screenshots to save in total (default: {DEFAULT_MAX_IMAGES})")
    p.add_argument("--no-frames", action="store_true", help="only print the event log")
    p.add_argument("--clean", action="store_true", help="delete the screenshots from an earlier run and exit")
    args = p.parse_args()

    meta_path = Path(args.metadata)
    out_dir = Path(args.out) if args.out else meta_path.parent / "director_frames"
    if args.clean:
        removed = clean(out_dir)
        print(f"Deleted {removed} screenshot(s)" + (f"; kept {out_dir} because it has other files in it"
                                                     if out_dir.exists() else ""))
        return

    with open(meta_path, encoding="utf-8") as f:
        recordings = json.load(f).get("recordings", [])
    if args.recording:
        recordings = [r for r in recordings if r["id"] in args.recording]
    if not recordings:
        sys.exit("No recordings found.")

    frames = not args.no_frames
    if frames:
        try:
            import cv2  # noqa: F401
        except ImportError:
            print("NOTE: opencv-python isn't installed for this Python, so no screenshots were saved.\n"
                  "      Install it with  pip install opencv-python  and run this again.")
            frames = False

    plans = [(rec, *key_moments(rec)) for rec in recordings]
    print(f"{len(recordings)} recording(s) in {meta_path}")
    print("Times are seconds into each recording. Click locations are in recording pixels.")
    for rec, _, notes in plans:
        print_recording(rec, notes)
    if not frames:
        return

    clean(out_dir)  # screenshots from an earlier run would be misleading
    out_dir.mkdir(parents=True, exist_ok=True)

    candidates = []
    for rec, moments, _ in plans:
        candidates += classify(moments, meta_path.parent / rec["file_name"])
    chosen, dropped = within_budget(candidates, args.max_images)
    counters = Counter()
    total_tokens = 0
    for m in chosen:
        counters[m.rec["id"]] += 1
        total_tokens += render(m, out_dir, counters[m.rec["id"]])

    print(f"\nKey screenshots ({len(chosen)}, about {total_tokens} tokens to view all) in {out_dir}:")
    for m in chosen:
        what = "full screen, new page or dialog" if m.kind == "overview" else "close-up around the click"
        print(f"  {m.path.name}  ({what})")
    if dropped:
        print(f"Not saved, to stay within --max-images {args.max_images}: "
              + ", ".join(m.label for m in dropped))
    print("Click screenshots are taken just before the click; the red crosshair marks the spot.")


if __name__ == "__main__":
    main()
