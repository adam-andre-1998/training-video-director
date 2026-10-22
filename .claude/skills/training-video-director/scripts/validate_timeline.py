"""
Validate a training video timeline.json against its recordings' metadata.json.

Checks the format described in references/timeline-format.md: segment order
and timing, that screen segments use real recordings and time ranges, that
each script fits its segment at the voice's speaking rate, that props sit
inside their segment and the recording's frame, and that every click shown
in a clip has an arrow and a click ripple.

Usage:
    python validate_timeline.py path/to/timeline.json
    python validate_timeline.py path/to/timeline.json --fix   # repair what it can, then check

--fix works out from the recordings what it can and rewrites the file: a
screen clip's duration from its clip range and speed; click arrows' and
ripples' targets, and ripples' start times, from their click events; an arrow
and a ripple for any click in a clip that has none (except double clicks and
clips sped up past 1.5x); props that run past their segment's end; and then
segment ids, starts and total_duration. It prints each change.
    python validate_timeline.py path/to/timeline.json --outline   # segment table, then the checks
    python validate_timeline.py timeline.json --metadata recordings/metadata.json

Exits with status 1 if there are errors.
"""

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

SEGMENT_TYPES = {"title_card", "cartoon_talking", "cartoon_silent", "screen_recording", "screen_still"}
SCREEN_TYPES = {"screen_recording", "screen_still"}
FLEXIBLE_DEFAULT = {"title_card": True, "cartoon_talking": True, "cartoon_silent": True,
                    "screen_still": True, "screen_recording": False}
PRESENTERS = {"none", "talking", "silent"}
DIRECTIONS = {"top", "bottom", "left", "right", "top-left", "top-right", "bottom-left", "bottom-right"}
ANCHORS = DIRECTIONS - {"left", "right"} | {"center"}
PROP_FIELDS = {
    "arrow": ["target", "from"],
    "click_ripple": ["target"],
    "highlight_box": ["box"],
    "zoom": ["center", "scale"],
    "callout": ["text"],
    "key_badge": ["keys"],
    "typing_caption": ["text"],
}
TOL = 0.05               # seconds of slack in timing comparisons
END_ROOM = 0.3           # narration should end at least this long before its segment does
TARGET_TOLERANCE = 20    # pixels between a click prop's target and the click event
PRESENTER_SHARE = 0.4   # warn when full-screen cartoon segments exceed this share of the video
ARROW_LEAD = 1.2         # recommended seconds an arrow appears before its click
REPEAT_DISTANCE = 30     # a click this close (px) ...
REPEAT_SECONDS = 1.0     # ... and this soon after the previous one repeats it (double click)
SPED_PAST = 1.5          # clips faster than this don't need an arrow on every click
TTS_UNFRIENDLY = re.compile(r"[\[\]{}<>*#_`|~@^=+\\]|https?://|\b(?:e\.g|i\.e|etc)\.", re.I)
EMOJI = re.compile("[☀-➿\U0001f000-\U0001faff]")


class Report:
    def __init__(self):
        self.errors, self.warnings = [], []
        self.missing_videos = set()  # recording ids already reported as missing

    def error(self, where, msg):
        self.errors.append(f"{where}: {msg}")

    def warn(self, where, msg):
        self.warnings.append(f"{where}: {msg}")


def num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def point_ok(p):
    return isinstance(p, list) and len(p) == 2 and all(num(v) for v in p)


def event_time(ev):
    return ev.get("timestamp", ev.get("start_timestamp", 0.0))


def fix_timing(timeline):
    t = 0.0
    for i, seg in enumerate(timeline.get("segments", []), 1):
        seg["id"] = i
        seg["start"] = round(t, 2)
        if num(seg.get("duration")):
            seg["duration"] = round(seg["duration"], 2)
            t += seg["duration"]
    timeline["total_duration"] = round(t, 2)


def arrow_side(location, size):
    """The side an arrow should come in from: the one facing the middle of the screen."""
    (x, y), (w, h) = location, size
    vertical = "bottom" if y < h * 0.4 else "top" if y > h * 0.6 else ""
    horizontal = "right" if x < w * 0.4 else "left" if x > w * 0.6 else ""
    return "-".join(p for p in (vertical, horizontal) if p) or "bottom"


def repeat_clicks(events):
    """Ids of clicks that repeat the click just before them (double and triple clicks)."""
    repeats, last = set(), None
    for ev in sorted(events, key=event_time):
        if ev.get("action") != "click":
            continue
        if (last and ev["timestamp"] - last["timestamp"] <= REPEAT_SECONDS
                and math.dist(ev["location"], last["location"]) <= REPEAT_DISTANCE):
            repeats.add(ev["id"])
        last = ev
    return repeats


def fix_segment(seg, rec, changes):
    """Fixes what follows from the recording: clip durations, click prop times and targets,
    missing arrows and ripples, and props running past their segment. Appends notes to changes."""
    where = f"segment {seg.get('id')}"
    src = seg.get("source") or {}
    if seg.get("type") == "screen_recording":
        cs, ce, speed = src.get("clip_start"), src.get("clip_end"), src.get("speed", 1.0)
        if not (num(cs) and num(ce) and num(speed) and ce > cs and speed > 0):
            return
        duration = round((ce - cs) / speed, 2)
        if not num(seg.get("duration")) or abs(seg["duration"] - duration) > 0.005:
            changes.append(f"{where}: duration {seg.get('duration')} -> {duration} (clip length / speed)")
            seg["duration"] = duration
    if not num(seg.get("duration")) or not isinstance(seg.get("props", []), list):
        return
    duration = seg["duration"]
    props = seg.setdefault("props", [])
    events = {ev.get("id"): ev for ev in rec.get("events", [])}
    in_clip = seg.get("type") == "screen_recording"

    for prop in props:
        if not isinstance(prop, dict):
            continue
        ev = events.get(prop.get("event_id"))
        if ev and ev.get("action") == "click" and prop.get("type") in ("arrow", "click_ripple"):
            if prop.get("target") != ev["location"]:
                changes.append(f"{where}: {prop['type']} for event {ev['id']} target -> {ev['location']}")
                prop["target"] = list(ev["location"])
            if in_clip and prop["type"] == "click_ripple" and num(prop.get("start")):
                et = round(to_segment_time(seg, ev["timestamp"]), 2)
                if 0 <= et < duration and abs(prop["start"] - et) > 0.05:
                    changes.append(f"{where}: click_ripple for event {ev['id']} start {prop['start']} -> {et}")
                    prop["start"] = et
        start, pdur = prop.get("start"), prop.get("duration")
        if num(start) and num(pdur) and 0 <= start < duration and start + pdur > duration + 0.005:
            new = round(duration - start, 2)
            changes.append(f"{where}: {prop.get('type')} duration {pdur} -> {new} (ended after the segment)")
            prop["duration"] = new

    if not in_clip or src.get("speed", 1.0) > SPED_PAST:
        return  # a sped-up stretch goes by too fast to point at each click
    linked = {}
    for prop in props:
        if isinstance(prop, dict) and "event_id" in prop:
            linked.setdefault(prop["event_id"], set()).add(prop.get("type"))
    repeats = repeat_clicks(rec.get("events", []))
    size = rec.get("resolution") or [1920, 1080]
    for ev in sorted(events.values(), key=event_time):
        if ev.get("action") != "click" or ev["id"] in repeats:
            continue
        et = round(to_segment_time(seg, ev["timestamp"]), 2)
        if not 0 <= et < duration:
            continue
        have = linked.get(ev["id"], set())
        if "arrow" not in have:
            start = round(max(et - ARROW_LEAD, 0), 2)
            props.append({"type": "arrow", "start": start,
                          "duration": round(min(et + 0.3, duration) - start, 2),
                          "target": list(ev["location"]), "from": arrow_side(ev["location"], size),
                          "event_id": ev["id"]})
            changes.append(f"{where}: added an arrow for click event {ev['id']} at {et}s")
        if "click_ripple" not in have:
            props.append({"type": "click_ripple", "start": et, "duration": round(min(0.6, duration - et), 2),
                          "target": list(ev["location"]), "event_id": ev["id"]})
            changes.append(f"{where}: added a click_ripple for click event {ev['id']} at {et}s")


def fix(timeline, timeline_path, metadata_override=None):
    """Applies every fix that can be worked out from the recordings, then the timing. Returns notes."""
    changes = []
    recordings, _ = load_metadata(timeline, timeline_path, metadata_override, Report())
    fix_timing(timeline)  # number the segments first, so the notes can name them
    for seg in timeline.get("segments") or []:
        if not isinstance(seg, dict) or seg.get("type") not in SCREEN_TYPES:
            continue
        rec = (recordings or {}).get((seg.get("source") or {}).get("recording_id"))
        if rec:
            fix_segment(seg, rec, changes)
    fix_timing(timeline)
    return changes


def load_metadata(timeline, timeline_path, override, r):
    meta_path = Path(override) if override else None
    if meta_path is None:
        rel = timeline.get("metadata_file")
        if not isinstance(rel, str) or not rel:
            r.error("timeline", "metadata_file is missing (or pass --metadata)")
            return None, None
        meta_path = timeline_path.parent / rel
    try:
        with open(meta_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        r.error("timeline", f"can't read metadata {meta_path}: {exc}")
        return None, None
    recordings = {rec.get("id"): rec for rec in data.get("recordings", [])}
    return recordings, meta_path


def check_top(timeline, r):
    if timeline.get("version") != 1:
        r.error("timeline", "version must be 1")
    for key in ("title", "summary", "audience"):
        if not isinstance(timeline.get(key), str) or not timeline.get(key, "").strip():
            (r.error if key == "title" else r.warn)("timeline", f"{key} is missing or empty")
    voice = timeline.get("voice", {})
    wpm = voice.get("words_per_minute", 150) if isinstance(voice, dict) else 150
    if not num(wpm) or not 80 <= wpm <= 250:
        r.error("timeline", "voice.words_per_minute must be a number between 80 and 250")
        wpm = 150
    segments = timeline.get("segments")
    if not isinstance(segments, list) or not segments:
        r.error("timeline", "segments must be a non-empty list")
        return wpm, []
    return wpm, segments


def check_timing(timeline, segments, r):
    expected = 0.0
    for i, seg in enumerate(segments, 1):
        where = f"segment {i}"
        if seg.get("id") != i:
            r.error(where, f"id is {seg.get('id')!r}, expected {i} (--fix renumbers)")
        if not num(seg.get("duration")) or seg["duration"] <= 0:
            r.error(where, "duration must be a positive number")
            continue
        if not num(seg.get("start")) or abs(seg["start"] - expected) > 0.01:
            r.error(where, f"start is {seg.get('start')!r}, expected {expected:.2f} "
                           "(previous start + duration; --fix recomputes)")
        if seg["duration"] < 1.0:
            r.warn(where, f"very short segment ({seg['duration']}s)")
        expected += seg["duration"]
    total = timeline.get("total_duration")
    if not num(total) or abs(total - expected) > 0.01:
        r.error("timeline", f"total_duration is {total!r}, expected {expected:.2f} (--fix recomputes)")


def check_script(seg, where, wpm, r):
    script = seg.get("script")
    if not isinstance(script, str):
        r.error(where, 'script must be a string (use "" for none)')
        return
    offset = seg.get("script_offset", 0)
    if not num(offset) or offset < 0:
        r.error(where, "script_offset must be a number >= 0")
        offset = 0
    flexible = seg.get("flexible", FLEXIBLE_DEFAULT.get(seg.get("type"), False))
    if not isinstance(flexible, bool):
        r.error(where, "flexible must be true or false")
    duration = seg.get("duration") if num(seg.get("duration")) else 0

    words = len(script.split())
    speech = words / (wpm / 60)
    needed = offset + speech + (END_ROOM if words else 0)
    if words and needed > duration + TOL:
        msg = (f"script is {words} words, about {speech:.1f}s of speech at {wpm} wpm"
               f"{f' after a {offset}s offset' if offset else ''}, but the segment is {duration}s "
               f"(needs about {needed:.1f}s)")
        if flexible:
            r.warn(where, msg + "; the assembler will have to stretch it")
        else:
            r.error(where, msg + "; shorten the script or change the clip")

    kind = seg.get("type")
    if kind == "cartoon_talking":
        if not words:
            r.error(where, "cartoon_talking needs a script")
        elif duration > 4 and speech < duration * 0.5:
            r.warn(where, f"script fills only {speech:.1f}s of {duration}s; the head would talk "
                          "over silence. Shorten the segment or use cartoon_silent for the rest")
    if kind == "cartoon_silent" and words:
        r.error(where, 'cartoon_silent must have an empty script ("")')

    bad = sorted({m.group(0) for m in TTS_UNFRIENDLY.finditer(script)} |
                 set(EMOJI.findall(script)))
    if bad:
        r.warn(where, f"script has text that TTS may read badly: {' '.join(bad)} "
                      "(spell shortcuts and symbols out, e.g. 'Control S')")


def check_source(seg, where, recordings, meta_path, r):
    """Checks a screen segment's source. Returns its recording, or None."""
    src = seg.get("source")
    if not isinstance(src, dict):
        r.error(where, "source is missing")
        return None
    if seg.get("presenter", "none") not in PRESENTERS:
        r.error(where, f"presenter must be one of {sorted(PRESENTERS)}")
    if recordings is None:
        return None
    rec = recordings.get(src.get("recording_id"))
    if rec is None:
        r.error(where, f"source.recording_id {src.get('recording_id')!r} is not in metadata.json")
        return None
    if src.get("file_name") != rec.get("file_name"):
        r.error(where, f"source.file_name should be {rec.get('file_name')!r} for recording {rec['id']}")
    elif meta_path and not (meta_path.parent / rec["file_name"]).exists() and rec["id"] not in r.missing_videos:
        r.missing_videos.add(rec["id"])
        r.warn(where, f"video file {rec['file_name']} not found next to metadata.json")
    rec_dur = rec.get("duration", 0)

    if seg.get("type") == "screen_recording":
        cs, ce, speed = src.get("clip_start"), src.get("clip_end"), src.get("speed", 1.0)
        if not (num(cs) and num(ce)) or not 0 <= cs < ce <= rec_dur + TOL:
            r.error(where, f"clip_start/clip_end must satisfy 0 <= clip_start < clip_end <= {rec_dur} "
                           f"(got {cs!r}, {ce!r})")
            return rec
        if not num(speed) or not 0.5 <= speed <= 3:
            r.error(where, "speed must be between 0.5 and 3")
            return rec
        expected = (ce - cs) / speed
        if num(seg.get("duration")) and abs(seg["duration"] - expected) > TOL:
            r.error(where, f"duration is {seg['duration']} but (clip_end - clip_start) / speed "
                           f"= {expected:.2f}")
    else:
        t = src.get("time")
        if not num(t) or not 0 <= t <= rec_dur:
            r.error(where, f"source.time must be between 0 and {rec_dur}")
    return rec


def to_segment_time(seg, t):
    src = seg["source"]
    return (t - src["clip_start"]) / src.get("speed", 1.0)


def check_props(seg, where, rec, r):
    props = seg.get("props", [])
    if not isinstance(props, list):
        r.error(where, "props must be a list")
        return
    kind = seg.get("type")
    duration = seg.get("duration") if num(seg.get("duration")) else 0
    width, height = (rec.get("resolution") or [math.inf, math.inf]) if rec else (math.inf, math.inf)
    events = {ev.get("id"): ev for ev in rec.get("events", [])} if rec else {}
    clip_ok = (kind == "screen_recording" and rec is not None
               and num(seg["source"].get("clip_start")) and num(seg["source"].get("speed", 1.0)))

    for j, prop in enumerate(props, 1):
        pw = f"{where} prop {j} ({prop.get('type', '?') if isinstance(prop, dict) else '?'})"
        if not isinstance(prop, dict) or prop.get("type") not in PROP_FIELDS:
            r.error(pw, f"type must be one of {sorted(PROP_FIELDS)}")
            continue
        ptype = prop["type"]
        missing = [k for k in PROP_FIELDS[ptype] if k not in prop]
        if missing:
            r.error(pw, f"missing {', '.join(missing)}")
            continue
        start, pdur = prop.get("start"), prop.get("duration")
        if not (num(start) and num(pdur)) or start < 0 or pdur <= 0:
            r.error(pw, "start must be >= 0 and duration > 0")
            continue
        if start + pdur > duration + TOL:
            r.error(pw, f"ends at {start + pdur:.2f}s, after its segment ends ({duration}s)")

        # Coordinates.
        points = []
        if ptype in ("arrow", "click_ripple") or (ptype == "callout" and "target" in prop):
            points.append(("target", prop.get("target")))
        if ptype == "zoom":
            points.append(("center", prop.get("center")))
        if points and kind not in SCREEN_TYPES:
            r.error(pw, "props with screen coordinates are only allowed on screen segments")
        for name, p in points:
            if not point_ok(p):
                r.error(pw, f"{name} must be [x, y]")
            elif not (0 <= p[0] < width and 0 <= p[1] < height):
                r.error(pw, f"{name} {p} is outside the recording's {width}x{height} frame")
        if ptype == "highlight_box":
            if kind not in SCREEN_TYPES:
                r.error(pw, "highlight_box is only allowed on screen segments")
            b = prop["box"]
            if not (isinstance(b, list) and len(b) == 4 and all(num(v) for v in b)) or b[2] <= 0 or b[3] <= 0:
                r.error(pw, "box must be [x, y, width, height] with positive size")
            elif b[0] < 0 or b[1] < 0 or b[0] + b[2] > width or b[1] + b[3] > height:
                r.error(pw, f"box {b} goes outside the recording's {width}x{height} frame")

        # Type-specific values.
        if ptype == "arrow" and prop["from"] not in DIRECTIONS:
            r.error(pw, f"from must be one of {sorted(DIRECTIONS)}")
        if ptype == "zoom" and not (num(prop["scale"]) and 1.2 <= prop["scale"] <= 3):
            r.error(pw, "scale must be between 1.2 and 3")
        if ptype == "callout":
            if "target" not in prop and prop.get("anchor") not in ANCHORS:
                r.error(pw, f"callout needs a target or an anchor from {sorted(ANCHORS)}")
            if len(str(prop["text"]).split()) > 10:
                r.warn(pw, "callout text is long; keep it under about 8 words")
        if ptype == "key_badge" and not (isinstance(prop["keys"], list) and prop["keys"]
                                         and all(isinstance(k, str) for k in prop["keys"])):
            r.error(pw, 'keys must be a list of key names, e.g. ["Ctrl", "S"]')
        if ptype in ("arrow", "highlight_box") and len(str(prop.get("label", "")).split()) > 4:
            r.warn(pw, "label is long; keep it to 1-3 words")

        # Link to a recorded event.
        if "event_id" not in prop:
            continue
        ev = events.get(prop["event_id"])
        if rec is None:
            if kind not in SCREEN_TYPES:
                r.error(pw, "event_id is only allowed on screen segments")
            continue  # on a screen segment, the bad source was already reported
        if ev is None:
            r.error(pw, f"event_id {prop['event_id']} is not an event of recording {rec['id']}")
            continue
        if ptype in ("arrow", "click_ripple") and ev["action"] == "click" and point_ok(prop.get("target")):
            dx, dy = prop["target"][0] - ev["location"][0], prop["target"][1] - ev["location"][1]
            if math.hypot(dx, dy) > TARGET_TOLERANCE:
                r.warn(pw, f"target {prop['target']} is {math.hypot(dx, dy):.0f}px from the click "
                           f"at {ev['location']}")
        if not clip_ok:
            continue
        et = to_segment_time(seg, event_time(ev))
        if not -TOL <= et <= duration + TOL:
            r.error(pw, f"event {ev['id']} happens at {et:.2f}s in this segment, outside the clip")
            continue
        if ptype == "click_ripple" and abs(start - et) > 0.15:
            r.warn(pw, f"ripple starts at {start}s but the click is at {et:.2f}s")
        if ptype == "arrow":
            if not start - TOL <= et <= start + pdur + TOL:
                r.warn(pw, f"arrow shows {start}-{start + pdur:.2f}s but the click is at {et:.2f}s")
            elif et - start < min(ARROW_LEAD, et) - 0.5:
                r.warn(pw, f"arrow appears only {et - start:.2f}s before the click; "
                           f"about {ARROW_LEAD}s gives viewers time to look")
        if ptype in ("typing_caption", "key_badge") and ev["action"] == "type":
            end = to_segment_time(seg, ev["end_timestamp"])
            if start > end + TOL or start + pdur < et - TOL:
                r.warn(pw, f"shown {start}-{start + pdur:.2f}s but the typing is at {et:.2f}-{end:.2f}s")


def check_click_coverage(seg, where, rec, r):
    """Every click inside a clip should have an arrow and a click ripple, except repeat clicks
    and clicks in a sped-up stretch."""
    src = seg["source"]
    cs, ce = src.get("clip_start"), src.get("clip_end")
    if not (num(cs) and num(ce)) or (num(src.get("speed", 1.0)) and src.get("speed", 1.0) > SPED_PAST):
        return
    linked = {}
    for prop in seg.get("props", []):
        if isinstance(prop, dict) and "event_id" in prop:
            linked.setdefault(prop["event_id"], set()).add(prop.get("type"))
    repeats = repeat_clicks(rec.get("events", []))
    for ev in rec.get("events", []):
        if ev.get("action") != "click" or not cs <= ev["timestamp"] <= ce or ev["id"] in repeats:
            continue
        missing = {"arrow", "click_ripple"} - linked.get(ev["id"], set())
        if missing:
            r.warn(where, f"click event {ev['id']} at {ev['timestamp']}s ({ev['location']}) has no "
                          f"{' or '.join(sorted(missing))} linked to it")


def validate(timeline, timeline_path, metadata_override=None):
    r = Report()
    wpm, segments = check_top(timeline, r)
    recordings, meta_path = load_metadata(timeline, timeline_path, metadata_override, r)
    if not segments:
        return r
    check_timing(timeline, segments, r)

    for i, seg in enumerate(segments, 1):
        if not isinstance(seg, dict):
            r.error(f"segment {i}", "must be an object")
            continue
        kind = seg.get("type")
        where = f"segment {i} ({kind})"
        if kind not in SEGMENT_TYPES:
            r.error(where, f"type must be one of {sorted(SEGMENT_TYPES)}")
            continue
        check_script(seg, where, wpm, r)
        rec = None
        if kind in SCREEN_TYPES:
            rec = check_source(seg, where, recordings, meta_path, r)
        elif "source" in seg or "presenter" in seg:
            r.warn(where, f"source/presenter are ignored on {kind} segments")
        if kind == "title_card":
            text = seg.get("text")
            if not isinstance(text, dict) or not str(text.get("title", "")).strip():
                r.error(where, "title_card needs text.title")
        check_props(seg, where, rec, r)
        if kind == "screen_recording" and rec is not None:
            check_click_coverage(seg, where, rec, r)

    presenter_time = sum(s["duration"] for s in segments if isinstance(s, dict)
                         and s.get("type") in ("cartoon_talking", "cartoon_silent") and num(s.get("duration")))
    total = sum(s["duration"] for s in segments if isinstance(s, dict) and num(s.get("duration")))
    if total and presenter_time / total > PRESENTER_SHARE:
        r.warn("timeline", f"the full-screen presenter takes up {presenter_time / total:.0%} of the video; "
                           "aim for about a third. Move narration onto screen segments (presenter: \"talking\")")
    return r


def clock(t):
    return f"{int(t // 60)}:{t % 60:04.1f}"


def print_outline(timeline):
    """One line per segment: where it is in the video, what it shows, its props and script."""
    voice = timeline.get("voice") if isinstance(timeline.get("voice"), dict) else {}
    wpm = voice.get("words_per_minute", 150) if num(voice.get("words_per_minute", 150)) else 150
    print(f"{timeline.get('title', '(untitled)')}: {timeline.get('total_duration', '?')}s, "
          f"{len(timeline.get('segments') or [])} segments")
    for seg in timeline.get("segments") or []:
        if not isinstance(seg, dict):
            continue
        start = seg.get("start", 0) if num(seg.get("start")) else 0
        dur = seg.get("duration", 0) if num(seg.get("duration")) else 0
        src = seg.get("source") if isinstance(seg.get("source"), dict) else {}
        if seg.get("type") == "screen_recording":
            what = (f"rec {src.get('recording_id')} {src.get('clip_start')}-{src.get('clip_end')}s"
                    + (f" x{src.get('speed')}" if src.get("speed", 1) != 1 else ""))
        elif seg.get("type") == "screen_still":
            what = f"rec {src.get('recording_id')} @ {src.get('time')}s"
        elif seg.get("type") == "title_card":
            what = repr((seg.get("text") or {}).get("title", ""))[:40]
        else:
            what = ""
        if seg.get("presenter", "none") != "none":
            what += f" +presenter {seg['presenter']}"
        kinds = Counter(p.get("type") for p in seg.get("props", []) if isinstance(p, dict))
        props = ", ".join(f"{n} {k}" for k, n in kinds.items()) or "-"
        script = " ".join(str(seg.get("script") or "").split())
        words = len(script.split())
        said = f'{words}w/{words / (wpm / 60):.1f}s "{script[:48]}{"..." if len(script) > 48 else ""}"' if words else "(silent)"
        print(f"  {seg.get('id', '?'):>3} {clock(start)}-{clock(start + dur)} {dur:5.1f}s "
              f"{str(seg.get('type', '?')):<16} {what:<30} props: {props:<28} {said}")
    print()


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("timeline", help="path to timeline.json")
    p.add_argument("--metadata", help="path to metadata.json (default: the timeline's metadata_file)")
    p.add_argument("--fix", action="store_true", help="rewrite segment ids, starts and total_duration")
    p.add_argument("--outline", action="store_true", help="print a one-line-per-segment outline first")
    args = p.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # scripts and typed text can have any characters

    path = Path(args.timeline)
    try:
        with open(path, encoding="utf-8") as f:
            timeline = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f"ERROR: can't read {path}: {exc}")
    if not isinstance(timeline, dict):
        sys.exit("ERROR: timeline must be a JSON object")

    if args.fix:
        changes = fix(timeline, path, args.metadata)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(timeline, f, indent=2, ensure_ascii=False)
            f.write("\n")
        for note in changes:
            print(f"FIXED    {note}")
        print(f"Rewrote ids, starts and total_duration ({timeline['total_duration']}s) in {path}\n")
    if args.outline:
        print_outline(timeline)

    report = validate(timeline, path, args.metadata)
    for msg in report.errors:
        print(f"ERROR    {msg}")
    for msg in report.warnings:
        print(f"WARNING  {msg}")
    segs = timeline.get("segments") or []
    print(f"\n{len(segs)} segments, {timeline.get('total_duration', '?')}s total: "
          f"{len(report.errors)} error(s), {len(report.warnings)} warning(s)")
    sys.exit(1 if report.errors else 0)


if __name__ == "__main__":
    main()
