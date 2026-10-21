"""
Summarize screen recordings for the training video director.

Prints every recording in a metadata.json with its events in time order,
including idle gaps, so the steps and the dead time to trim are easy to see.
Uses only the Python standard library.

Usage:
    python inspect_recordings.py path/to/metadata.json
    python inspect_recordings.py path/to/metadata.json --recording 2
"""

import argparse
import json
import sys
from pathlib import Path

GAP_NOTE = 3.0  # report idle gaps longer than this many seconds


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


def print_recording(rec):
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
        print(f"    {ev['id']:>3}  {describe(ev)}")
        prev_end = ev.get("end_timestamp", ev.get("timestamp", prev_end))
    tail = rec["duration"] - prev_end
    if tail > GAP_NOTE:
        print(f"         ... idle {tail:.1f}s until the end ...")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("metadata", help="path to metadata.json")
    p.add_argument("--recording", type=int, action="append", help="only this recording id (repeatable)")
    args = p.parse_args()

    meta_path = Path(args.metadata)
    with open(meta_path, encoding="utf-8") as f:
        recordings = json.load(f).get("recordings", [])
    if args.recording:
        recordings = [r for r in recordings if r["id"] in args.recording]
    if not recordings:
        sys.exit("No recordings found.")

    print(f"{len(recordings)} recording(s) in {meta_path}")
    print("Times are seconds into each recording. Click locations are in recording pixels.")
    for rec in recordings:
        print_recording(rec)


if __name__ == "__main__":
    main()
