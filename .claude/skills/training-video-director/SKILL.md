---
name: training-video-director
description: Directs a narrated training video from screen recordings. Takes the metadata.json written by screen_recorder.py (clicks and typing with timestamps) plus context about what the video should teach, and writes a timeline.json that cuts the recordings into segments (screen recordings, freeze-frames, talking or silent cartoon presenter, title cards), writes the text-to-speech script for each segment, and places props such as arrows, click ripples, zooms and captions on what the user clicked and typed. Use when asked to make, plan, script or direct a training video, tutorial or walkthrough from recordings, or to create or update a timeline.json.
---

# Training video director

You are the director of a short training video. You receive raw screen
recordings and their input events, and produce `timeline.json`: a complete
edit decision list that a separate Python + ffmpeg assembler turns into the
finished video. **Your output is the timeline only.** Don't render video,
generate audio or edit the recordings.

How the assembler uses the timeline:

- `screen_recording` and `screen_still` segments are shown inside a laptop
  frame.
- `cartoon_talking` shows the presenter, a cartoon woman seated at an office
  desk, talking with her mouth synced to the narration.
- `cartoon_silent` shows the same presenter, breathing and blinking but not
  talking.
- `title_card` shows text full screen.
- Each segment's `script` is turned into speech and placed at that
  segment's start (plus `script_offset`).
- Props are drawn on top at the times and positions you give.

## Files in this skill

The paths below are relative to this skill's folder.

- `references/timeline-format.md`: the exact timeline.json format. **Read it
  before writing a timeline.**
- `references/directing-guide.md`: structure, pacing, props and script
  rules. **Read it before planning.**
- `scripts/inspect_recordings.py`: prints a readable event log for each
  recording, with idle gaps marked, and saves a screenshot at every click
  and typing action so you can see what was clicked.
- `scripts/validate_timeline.py`: checks a timeline against metadata.json
  and fixes start times.
- `assets/example-timeline.json` and `assets/example-metadata.json`: a
  complete worked example. It has no video file, so the validator warns
  about that, and only that.

Run the scripts with the `python` that's already available. **Don't create a
virtual environment.** The validator needs only the standard library. The
inspector's screenshots need `opencv-python`, which is in the project's
requirements.txt. If the inspector says it's missing, run
`pip install opencv-python` once, then rerun the inspector.

Timing and coordinates always come from metadata.json. The screenshots are
for seeing *what* each click hit, such as button labels, menus and fields.
Don't open or play the video files any other way.

## Inputs

1. **metadata.json**: the recordings folder's metadata file. Ask for its path
   if it isn't given and isn't obvious (look for `recordings/metadata.json`).
2. **Context**: what the video teaches, who it's for, product names, tone,
   target length, anything to emphasize or avoid. Use whatever the user
   gives. If they give nothing, infer the topic from recording
   descriptions, window titles and typed text, and state your assumptions at
   the end. Only ask a question when you can't tell what the video is about.
3. **Which recordings**: by default, every recording in metadata.json in `id`
   order. Use a subset or different order if the user says so or the
   descriptions make it obvious.

## Workflow

1. **Read the references**: `references/timeline-format.md` and
   `references/directing-guide.md`.

2. **Inspect the recordings:**

   ```bash
   python <skill-dir>/scripts/inspect_recordings.py <path/to/metadata.json>
   ```

   This prints each recording's events in order, with idle gaps marked, and
   saves a few key screenshots to `<recordings folder>/director_frames/`. It
   ends with a **Key screenshots** list and an estimate of their token cost.
   To keep that cost low, it skips screenshots that wouldn't add anything,
   and the event log notes why next to each skipped event:
   - repeat clicks on the same spot share one screenshot;
   - starting and stopping the recorder (a different window at the very
     start or end) gets none;
   - typing gets none, because the typed text is in the log.

   Each screenshot is taken just before its click, with a red crosshair on
   the spot. There are two kinds:
   - `..._overview_...`: the full screen, saved when it changed a lot (a new
     page or dialog), with an enlarged view of the click area in a corner;
   - `..._detail_...`: a close-up around the click, for clicks on a screen
     already shown.

   At most 12 are saved (`--max-images N` to change that). Lower it for long
   recordings if you only need the main screens.

   **Open only the files in the Key screenshots list**, in order, and don't
   browse the folder for others. Use them to name what was clicked
   exactly as it appears on screen ("New", "Blank presentation", "Untitled
   presentation"), to understand each step, and to choose `highlight_box`
   areas and arrow directions that point away from busy parts of the screen.
   The event log, window titles and typed text fill in the rest. If you can't
   view images, work from those alone, and keep the wording general where
   you're unsure ("click the button in the top right") rather than guessing a
   name.

   The screenshots show the user's real screen. Use them only to direct the
   video: don't copy names, email addresses or other personal details from
   them into the script or props.

3. **Plan the video before writing JSON.** Work out:
   - the steps of the task, and which events and recording time ranges
     belong to each;
   - where to trim dead time, and where to slow down or add a freeze-frame;
   - where the presenter appears (intro, bridges, recap, outro);
   - the props for each click and typing action.

4. **Write the script** for every segment, following the TTS and timing
   rules in the directing guide. Fit each script to its segment's duration.

5. **Write `timeline.json`** next to metadata.json, unless the user names
   another path. If a timeline.json already exists there, ask before
   overwriting it, or write `timeline_<short-topic>.json` instead. Set
   `metadata_file` to the path of metadata.json relative to the timeline.

6. **Validate and fix** until there are no errors:

   ```bash
   python <skill-dir>/scripts/validate_timeline.py <path/to/timeline.json> --fix
   ```

   `--fix` rewrites segment `id`, `start` and `total_duration` from the
   durations. Every other problem it reports, you fix by editing the timeline.
   Fix every error. Fix warnings too, unless you have a reason not to (for
   example, a click deliberately sped past without an arrow), and mention any
   you leave.

7. **Report back** briefly:
   - where the timeline is and its total length;
   - a short outline of the segments (type, length, one line each);
   - any assumptions you made and any warnings you left in place.

   Don't paste the whole JSON.

## Rules that matter most

- Every screen clip and still must use a real recording: its `id` and
  `file_name` from metadata.json, and times inside its `duration`.
- A `screen_recording`'s `duration` is `(clip_end - clip_start) / speed`.
  Never stretch it to fit a long script. Shorten the script, slow the clip
  down, or add a `screen_still` instead.
- Prop times are relative to the segment, and coordinates are in the
  recording's pixel space. Use the event's `location` exactly for clicks.
- Every click shown in a clip gets an `arrow` and a `click_ripple` tied to
  it by `event_id`.
- `cartoon_silent` has no script. `cartoon_talking` always has one.
- Never put passwords, tokens or other secrets in the script or props.
