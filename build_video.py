"""
Build a narrated training video from a director timeline.json.

    python build_video.py recordings/timeline.json
    python build_video.py recordings/timeline.json -o demo.mp4 --voice af_bella
    python build_video.py recordings/timeline.json --preview      # fast, half size
    python build_video.py --list-voices

Steps: generate narration with text-to-speech (Kokoro by default), lengthen
any segment whose narration runs long, mix the narration track, then render
every frame (screen recordings inside a laptop, the presenter lip-synced to the
narration, title cards and props) and encode it with ffmpeg.
"""

import argparse
import re
import time
from pathlib import Path

from video_builder import audio, timeline as tl, tts
from video_builder.config import FPS, HEIGHT, WIDTH
from video_builder.ffmpeg import VideoWriter
from video_builder.render import Renderer


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "video"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("timeline", nargs="?", help="path to timeline.json")
    p.add_argument("-o", "--output", help="output .mp4 (default: <title>.mp4 next to the timeline)")
    p.add_argument("--tts", choices=["kokoro", "windows"], default="kokoro",
                   help="text-to-speech engine (default: kokoro)")
    p.add_argument("--voice", help="voice name: a Kokoro voice like af_heart, or part of a Windows voice name")
    p.add_argument("--preview", action="store_true", help="render at 960x540, 15 fps for a quick look")
    p.add_argument("--list-voices", action="store_true", help="list the voices for --tts and exit")
    args = p.parse_args()

    if args.list_voices:
        print("\n".join(tts.list_voices(args.tts)))
        return
    if not args.timeline:
        p.error("timeline is required")

    width, height, fps = (960, 540, 15) if args.preview else (WIDTH, HEIGHT, FPS)
    timeline = tl.load(args.timeline)
    output = Path(args.output) if args.output else timeline.path.parent / f"{slug(timeline.title)}.mp4"
    build_dir = timeline.path.parent / ".build" / timeline.path.stem
    build_dir.mkdir(parents=True, exist_ok=True)

    print(f"Narrating {sum(1 for s in timeline.segments if s.script.strip())} segment(s) with {args.tts}...")
    speech = tts.synthesize({s.id: s.script for s in timeline.segments}, build_dir / "tts",
                            timeline.words_per_minute, args.voice, args.tts)
    for seg in timeline.segments:
        if seg.id in speech:
            seg.audio_path, seg.speech = speech[seg.id]
    for note in tl.fit_to_speech(timeline):
        print(f"  {note}")

    narration = audio.build_narration(
        [(seg.start + seg.script_offset, seg.audio_path) for seg in timeline.segments if seg.audio_path],
        timeline.duration, build_dir / "narration.wav")
    total = int(round(timeline.duration * fps))
    loudness = audio.loudness(narration, fps, total)

    print(f"Rendering {timeline.duration:.1f}s at {width}x{height} {fps} fps -> {output}")
    renderer = Renderer(timeline, width, height, fps, loudness)
    writer = VideoWriter(output, width, height, fps, audio=narration, log_path=build_dir / "ffmpeg.log")
    started = time.time()
    try:
        for i, frame in enumerate(renderer.frames(), 1):
            writer.write(frame)
            if i % (fps * 5) == 0 or i == total:
                elapsed = time.time() - started
                print(f"  {i / fps:6.1f}s / {timeline.duration:.1f}s  ({elapsed:.0f}s elapsed)", flush=True)
    finally:
        writer.close()
    print(f"Done: {output}")


if __name__ == "__main__":
    main()
