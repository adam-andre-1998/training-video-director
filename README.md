# Training video director

Turns screen recordings into a narrated training video, with a cartoon
presenter, arrows on every click and captions for what you type.

## Making a video

1. **Record** the steps, one take per step:

   ```bash
   python screen_recorder.py my-video
   ```

   Set up the screen, press **F9** to start a take and **F9** again to stop
   it; this works from any window, so the recorder never shows up in the
   video. After each take, describe it in a few words (or type `redo` to
   throw it away). Press **Ctrl+C** in the recorder's window when you're done.
   Takes go in `recordings/my-video/`.

2. **Ask Claude Code** for the video, with whatever context helps:

   > make a training video from recordings/my-video, for new staff, about a minute long

   Claude reads the recordings, writes the script and shows it to you with
   cues for what's on screen. Reply with changes, or say "looks good". (Say
   "no need to review the script" up front to skip this.)

3. **Watch it.** Claude builds `output/<title>.mp4` and opens it. Reply with
   any changes ("shorten the intro", "the arrow at 0:23 is wrong") and Claude
   revises and rebuilds.

## Tools

| | |
|---|---|
| `screen_recorder.py [name]` | Records takes to `recordings/<name>/` with their clicks and typing in `metadata.json`. `--now -d 30` records one 30-second take straight away. |
| `build_video.py [timeline.json]` | Renders a timeline (default: the newest one under `recordings/`) and opens the video. `--preview` for a quick half-size render, `--no-open` to just save it, `--list-voices`, `--voice af_bella`. |
| `.claude/skills/training-video-director/` | The Claude Code skill that directs the video: event log and screenshots (`inspect_recordings.py`), the timeline format, and a validator that repairs what it can (`validate_timeline.py --fix`). |

Narration is spoken offline by Kokoro (`assets/tts/kokoro/`); each line's
audio is cached in `.cache/tts/` so rebuilds only speak the lines that changed.
The builder renders up to 8 parts of the video at once (`--jobs N` to change
that), so a full-quality build takes well under the video's length.
Recordings, timelines and videos are personal and are never committed.

## Setup

```bash
pip install -r requirements.txt
```

Windows; ffmpeg is used from your PATH, or the copy that comes with
`imageio-ffmpeg`.
