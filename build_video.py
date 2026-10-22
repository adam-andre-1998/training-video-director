"""
Build a narrated training video from a director timeline.json.

    python build_video.py                                   # the newest recordings/**/timeline.json
    python build_video.py recordings/google-slides/timeline.json
    python build_video.py recordings/timeline.json -o demo.mp4 --voice af_bella
    python build_video.py recordings/timeline.json --preview      # fast, half size
    python build_video.py --list-voices

Steps: generate narration with text-to-speech (Kokoro, or the built-in
Windows voices where the Kokoro model files aren't available), lengthen
any segment whose narration runs long, mix the narration track, then render
every frame (screen recordings inside a laptop, the presenter lip-synced to the
narration, title cards and props), encode it with ffmpeg, and open the video.

The video is saved to output/<title>.mp4 unless -o says otherwise. Narration
for each line is cached in .cache/tts/, so a rebuild only speaks the lines
that changed. Other working files go in a temporary folder that is deleted
when the build finishes, so the recordings folder is left untouched.
"""

import argparse
import os
import re
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from video_builder import audio, timeline as tl, tts
from video_builder.config import FPS, HEIGHT, OUTPUT_DIR, RECORDINGS_DIR, TTS_CACHE, WIDTH
from video_builder.ffmpeg import VideoWriter, concat
from video_builder.render import Renderer

MIN_PART = 3.0  # seconds: shorter parts cost more in start-up than they save


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "video"


def clock(seconds):
    return f"{int(seconds // 60)}:{seconds % 60:04.1f}"


def newest_timeline():
    """The most recently changed timeline*.json under recordings/, or None."""
    found = [p for p in RECORDINGS_DIR.glob("**/timeline*.json") if p.is_file()]
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def writable(output):
    """`output`, or a numbered sibling if a video player has the file open (Windows locks it)."""
    for n in range(1, 50):
        candidate = output if n == 1 else output.with_name(f"{output.stem} ({n}){output.suffix}")
        try:
            with open(candidate, "ab"):
                pass
            if candidate != output:
                print(f"{output.name} is open in another program; saving as {candidate.name} instead")
            return candidate
        except PermissionError:
            continue
    raise SystemExit(f"Can't write {output}: close the program that has it open")


def open_file(path):
    try:
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            os.spawnlp(os.P_NOWAIT, "open", "open", str(path))
        else:
            os.spawnlp(os.P_NOWAIT, "xdg-open", "xdg-open", str(path))
    except OSError as exc:
        print(f"(couldn't open the video: {exc})")


def build(timeline, output, work_dir, width, height, fps, tts_engine, voice, cache_dir, jobs):
    print(f"Narrating {sum(1 for s in timeline.segments if s.script.strip())} segment(s) with {tts_engine}...")
    speech, reused = tts.synthesize({s.id: s.script for s in timeline.segments}, work_dir / "tts",
                                    timeline.words_per_minute, voice, tts_engine, cache_dir)
    if reused:
        print(f"  {reused} line(s) unchanged since an earlier build, reused their audio")
    for seg in timeline.segments:
        if seg.id in speech:
            seg.audio_path, seg.speech = speech[seg.id]
    for note in tl.fit_to_speech(timeline):
        print(f"  {note}")

    narration = audio.build_narration(
        [(seg.start + seg.script_offset, seg.audio_path) for seg in timeline.segments if seg.audio_path],
        timeline.duration, work_dir / "narration.wav")
    total = int(round(timeline.duration * fps))
    loudness = audio.loudness(narration, fps, total)

    # Split the frames into parts of at least MIN_PART seconds, one per process.
    jobs = max(1, min(jobs, total // int(MIN_PART * fps)))
    bounds = [round(total * k / jobs) for k in range(jobs + 1)]
    print(f"Rendering {timeline.duration:.1f}s at {width}x{height} {fps} fps"
          + (f" in {jobs} parts at once" if jobs > 1 else "") + f" -> {output}")
    started = time.time()
    if jobs == 1:
        render_part(timeline, width, height, fps, loudness, 0, total, output, narration)
        return

    parts = [work_dir / f"part_{k:02d}.ts" for k in range(jobs)]
    done = 0
    with ProcessPoolExecutor(jobs) as pool:
        futures = [pool.submit(render_part, timeline, width, height, fps, loudness, a, b, part)
                   for a, b, part in zip(bounds, bounds[1:], parts)]
        for future in as_completed(futures):
            done += future.result()
            print(f"  {done / fps:6.1f}s / {timeline.duration:.1f}s  ({time.time() - started:.0f}s elapsed)",
                  flush=True)
    concat(parts, narration, output, work_dir)


def render_part(timeline, width, height, fps, loudness, first, last, path, narration=None):
    """Renders frames first..last-1 to their own video file. Returns the number of frames.

    Runs in a worker process, so it builds its own Renderer.
    """
    renderer = Renderer(timeline, width, height, fps, loudness)
    writer = VideoWriter(path, width, height, fps, audio=narration, log_path=Path(path).with_suffix(".log"))
    try:
        for frame in renderer.frames(first, last):
            writer.write(frame)
    finally:
        writer.close()
    return last - first


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("timeline", nargs="?",
                   help="path to timeline.json (default: the newest timeline*.json under recordings/)")
    p.add_argument("-o", "--output", help="output .mp4 (default: output/<title>.mp4 in the project)")
    p.add_argument("--tts", choices=tts.ENGINES, default="auto",
                   help="text-to-speech engine (default: auto = kokoro if its model files are found, "
                        "else windows)")
    p.add_argument("--voice", help="voice name: a Kokoro voice like af_heart, or part of a Windows voice name")
    p.add_argument("--preview", action="store_true", help="render at 960x540, 15 fps for a quick look")
    p.add_argument("--no-open", action="store_true", help="don't open the video when it's done")
    p.add_argument("--no-cache", action="store_true", help="speak every line again instead of reusing audio")
    p.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 1),
                   help="render this many parts of the video at once (default: up to 8, one per CPU)")
    p.add_argument("--list-voices", action="store_true", help="list the voices for --tts and exit")
    args = p.parse_args()

    if args.list_voices:
        print("\n".join(tts.list_voices(args.tts)))
        return
    timeline_path = Path(args.timeline) if args.timeline else newest_timeline()
    if timeline_path is None:
        p.error(f"no timeline given and none found under {RECORDINGS_DIR}")
    if not args.timeline:
        print(f"Building {timeline_path}")

    engine, voice = tts.resolve_engine(args.tts, args.voice)
    width, height, fps = (960, 540, 15) if args.preview else (WIDTH, HEIGHT, FPS)
    timeline = tl.load(timeline_path)
    output = Path(args.output) if args.output else OUTPUT_DIR / f"{slug(timeline.title)}.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)
    output = writable(output)

    with tempfile.TemporaryDirectory(prefix="training-video-") as work_dir:
        try:
            build(timeline, output, Path(work_dir), width, height, fps, engine, voice,
                  None if args.no_cache else TTS_CACHE, args.jobs)
        except BaseException:
            output.unlink(missing_ok=True)  # don't leave a half-written video behind
            raise
    print(f"Done: {output} ({clock(timeline.duration)})")
    if not args.no_open:
        open_file(output)


if __name__ == "__main__":
    main()
