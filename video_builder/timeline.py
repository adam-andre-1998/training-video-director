"""Loading timeline.json and its recordings, and fitting segments to the narration."""

import json
from dataclasses import dataclass, field
from pathlib import Path

from .config import SPEECH_TAIL

SCREEN_TYPES = {"screen_recording", "screen_still"}
FLEXIBLE_DEFAULT = {"title_card": True, "cartoon_talking": True, "cartoon_silent": True,
                    "screen_still": True, "screen_recording": False}


@dataclass
class Segment:
    id: int
    type: str
    start: float
    duration: float
    script: str = ""
    script_offset: float = 0.0
    flexible: bool = True
    props: list = field(default_factory=list)
    source: dict = field(default_factory=dict)
    presenter: str = "none"
    text: dict = field(default_factory=dict)
    recording: dict = None     # the metadata.json entry for screen segments
    speech: float = 0.0        # length of the generated narration audio
    audio_path: Path = None
    clip_duration: float = 0.0  # planned length of a screen_recording clip before any stretch

    @property
    def end(self):
        return self.start + self.duration

    def event_time(self, event, key="timestamp"):
        """Segment time at which a recording event happens (screen_recording only)."""
        t = event.get(key, event.get("start_timestamp", 0.0))
        return (t - self.source["clip_start"]) / self.source.get("speed", 1.0)


@dataclass
class Timeline:
    path: Path
    title: str
    words_per_minute: float
    segments: list
    recordings_dir: Path

    @property
    def duration(self):
        return self.segments[-1].end if self.segments else 0.0


def load(path):
    path = Path(path)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    meta_path = path.parent / data.get("metadata_file", "metadata.json")
    with open(meta_path, encoding="utf-8") as f:
        recordings = {r["id"]: r for r in json.load(f).get("recordings", [])}

    segments = []
    for raw in data["segments"]:
        kind = raw["type"]
        seg = Segment(
            id=raw["id"], type=kind, start=float(raw["start"]), duration=float(raw["duration"]),
            script=raw.get("script", "") or "", script_offset=float(raw.get("script_offset", 0)),
            flexible=raw.get("flexible", FLEXIBLE_DEFAULT.get(kind, True)),
            props=raw.get("props", []), source=raw.get("source", {}),
            presenter=raw.get("presenter", "none"), text=raw.get("text", {}),
        )
        if kind in SCREEN_TYPES:
            seg.recording = recordings.get(seg.source.get("recording_id"))
            if seg.recording is None:
                raise ValueError(f"Segment {seg.id}: recording {seg.source.get('recording_id')} "
                                 f"is not in {meta_path}")
        if kind == "screen_recording":
            seg.clip_duration = seg.duration
        segments.append(seg)

    return Timeline(path=path, title=data.get("title", path.stem), segments=segments,
                    words_per_minute=data.get("voice", {}).get("words_per_minute", 150),
                    recordings_dir=meta_path.parent)


def fit_to_speech(timeline):
    """Lengthens segments whose narration came out longer than planned, then re-flows start times.

    Flexible segments simply get longer. A screen_recording that overflows
    holds its last frame for the extra time. Returns notes about each change.
    """
    notes = []
    t = 0.0
    for seg in timeline.segments:
        needed = seg.script_offset + seg.speech + SPEECH_TAIL if seg.speech else 0
        if needed > seg.duration + 0.01:
            how = "stretched" if seg.flexible else "last frame held"
            notes.append(f"segment {seg.id} ({seg.type}): narration is {seg.speech:.1f}s, "
                         f"segment {seg.duration:.1f}s -> {needed:.1f}s ({how})")
            seg.duration = round(needed, 3)
        seg.start = t
        t += seg.duration
    return notes
