---
name: training-video-director
description: Directs a narrated training video from screen recordings and builds it. Takes the metadata.json written by screen_recorder.py (clicks and typing with timestamps) plus context about what the video should teach, and writes a timeline.json that cuts the recordings into segments (screen recordings, freeze-frames, talking or silent cartoon presenter, title cards), writes the text-to-speech script for each segment, and places props such as arrows, click ripples, zooms and captions on what the user clicked and typed. Shows the user the full script, with cues for what is on screen, and waits for their approval before writing the timeline, then renders the finished MP4 with build_video.py and opens it. Also revises an existing timeline.json in place and rebuilds, from requests or feedback on the built video ("shorten the intro", "the arrow at 0:23 is wrong", "reword the recap", "I re-recorded step 2"). Use when asked to make, plan, script, direct, build, revise, edit or fix a training video, tutorial or walkthrough from recordings, or a timeline.json.
---

# Training video director

You are the director of a short training video. You receive raw screen
recordings and their input events, and produce `timeline.json`: a complete
edit decision list that the project's Python + ffmpeg assembler
(`build_video.py`) turns into the finished video. Once the timeline is valid
you run the assembler yourself, so the user's only jobs are recording,
approving the script and watching the result. Don't generate audio or edit
the recordings any other way.

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
  recording, with idle gaps marked, and saves key screenshots to a temp
  folder so you can see what was clicked.
- `scripts/validate_timeline.py`: checks a timeline against metadata.json.
  With `--fix`, it first repairs everything that follows from the
  recordings (see Workflow step 6). With `--outline`, it first prints the
  timeline as a compact table.
- `build_video.py`, in the project root (the folder with `screen_recorder.py`,
  usually three levels above this skill's folder): renders the timeline to
  `output/<title>.mp4` and opens it.
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

1. **metadata.json**: the recordings folder's metadata file. The recorder
   keeps each video's takes in its own folder, `recordings/<video-name>/`,
   and prints the metadata path when it finishes. If the user doesn't give
   one, use the most recently changed `recordings/**/metadata.json`, say
   which one in your first reply, and carry on. Ask only if there's none.
2. **Context**: what the video teaches, who it's for, product names, tone,
   target length, anything to emphasize or avoid. Use whatever the user
   gives. If they give nothing, infer the topic from recording
   descriptions, window titles and typed text, and state your assumptions at
   the end. Only ask a question when you can't tell what the video is about.
3. **Which recordings**: by default, every recording in metadata.json in `id`
   order. Use a subset or different order if the user says so or the
   descriptions make it obvious.

## New timeline or revision?

- If the user wants **changes to a video or timeline that already exists**
  (feedback on the built video, "make it shorter", "change the voice
  rate", "fix the arrow", "use my new recording for step 2"), follow
  **Revising an existing timeline** below. Edit that timeline in place;
  that's what they asked for.
- If they want **a new video** and a timeline already exists where you
  would write it, ask whether to replace it or write
  `timeline_<short-topic>.json` alongside it.
- Otherwise follow **Workflow**.

## Workflow

1. **Read the references**: `references/timeline-format.md` and
   `references/directing-guide.md`.

2. **Inspect the recordings:**

   ```bash
   python <skill-dir>/scripts/inspect_recordings.py <path/to/metadata.json>
   ```

   This prints each recording's events in order, with idle gaps marked, and
   saves a few key screenshots to a folder in the system temp folder (never
   the recordings folder). It ends with a **Key screenshots** list, with that
   folder's path, and an estimate of their token cost.
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
   Then **delete the screenshots**; you've taken what you need from them:

   ```bash
   python <skill-dir>/scripts/inspect_recordings.py <path/to/metadata.json> --clean
   ```

   If later feedback means you need to see the screen again, rerun the
   inspector for just that recording, and clean up again afterwards.

5. **Get the script approved.** Show the user the full script in the
   **Script review** format below, then **stop and wait for their reply.
   Don't write timeline.json yet.**
   - If the user said up front that they don't need to review the script
     ("just make it", "no need to check with me", "build it straight
     away"), skip the review and go on to step 6. The Script review then
     goes in your report at the end instead, so they still see every line.
   - If they ask for changes, apply them to your plan, then show the
     **whole** updated script again, marking each changed segment
     `(changed)`. Wait again. Repeat as often as they like.
   - Changes that affect timing (a longer line, a new segment, slowing a
     clip) are part of the plan too: update the durations and times in the
     script you show.
   - Only a clear approval moves you on: "looks good", "good", "approved",
     "continue", "go ahead", "yes", "ship it" and the like. A reply that
     approves *and* asks for a change ("good, but shorten the intro") is a
     change request: apply it and show the script again. If you can't tell
     whether they approved, ask.
   - Questions about the script aren't approval: answer them, then ask
     again whether the script is good to go.

6. **Write `timeline.json`** from the approved script, next to metadata.json
   unless the user names another path (see **New timeline or revision?** if
   one already exists). Use the approved narration **word for word**, and
   keep the segments, order and on-screen actions they approved. Set
   `metadata_file` to the path of metadata.json relative to the timeline.

   You don't need to work out everything by hand: the validator's `--fix`
   fills in what follows from the recordings. Give each click an `arrow`
   when you want a `label` or a particular `from` side, and leave the rest
   to `--fix`, which:
   - sets each `screen_recording`'s `duration` to
     `(clip_end - clip_start) / speed`;
   - sets the `target` of click arrows and ripples to their event's
     location, and each ripple's `start` to the moment of its click;
   - adds an `arrow` (no label, coming in from the side facing the middle
     of the screen) and a `click_ripple` for every click in a clip that
     lacks one, except repeat clicks (double clicks) and clips sped up past
     1.5x;
   - shortens props that run past their segment's end;
   - renumbers ids and recomputes every `start` and `total_duration`.

7. **Validate and fix** until there are no errors:

   ```bash
   python <skill-dir>/scripts/validate_timeline.py <path/to/timeline.json> --fix
   ```

   It prints a `FIXED` line for each change, then any remaining problems.
   Fix every error by editing the timeline. Fix warnings too, unless you
   have a reason not to, and mention any you leave.

   Fix timing problems by changing timing (segment durations, clip ranges or
   speed, props), not the approved narration. If the narration itself has to
   change (for example, a line can't fit its clip at any reasonable speed),
   show the user the affected segments with the new wording and wait for
   their OK before saving it.

   Don't create any other files in the recordings folder (notes, drafts,
   backups); keep the plan and script in the conversation.

8. **Build the video**, from the project root:

   ```bash
   python build_video.py <path/to/timeline.json>
   ```

   It speaks the narration, renders at 1920x1080, saves
   `output/<title>.mp4` and opens it for the user. It renders several parts
   of the video at once and usually takes less than half the video's
   length; for a long video, run it in the background if you can, and wait
   for it to finish. Lines spoken in an earlier build are reused, so
   rebuilds are faster still. It prints a line for each segment it had
   to lengthen because the real narration ran long; note those for your
   report. If it fails, fix the cause and build again; don't hand the user
   a command to run instead.

9. **Report back** briefly:
    - where the video is and how long it is, and where the timeline is;
    - any timing that changed while validating or building, compared with
      the approved script (segments the builder lengthened, for example);
    - any assumptions you made and any warnings you left in place;
    - that they can reply with changes ("shorten the intro", "the arrow at
      0:23 is wrong"), and you'll revise and rebuild.

    If the user approved the script, don't repeat it. If they skipped the
    review, include the script in the **Script review** format. Don't paste
    the JSON.

## Script review

Show the script as plain text in chat, one block per segment, in video
order. Each block starts with a **cue** that says what the viewer sees:

| Cue | Segment |
|---|---|
| `[TITLE CARD]` | `title_card` |
| `[PRESENTER - on camera]` | `cartoon_talking`: the narration is the presenter talking to camera |
| `[PRESENTER - silent]` | `cartoon_silent` |
| `[SCREEN - recording N, m:ss-m:ss]` | `screen_recording`: voice-over on the screen recording. Add `, slowed to 0.75x` or `, sped up 2x` when the speed isn't 1 |
| `[SCREEN STILL - recording N at m:ss]` | `screen_still`: voice-over on a freeze-frame |
| `+ presenter in corner` | added to a SCREEN cue when `presenter` is `"talking"` |

After the cue comes the segment's approximate place in the video. Below it:
- **On screen:** title card text, or the action and the props in plain
  words ("arrow and click on New, then Google Slides", "caption shows
  'New Presentation'", "zoom on the title box");
- **Narration:** the exact words to be spoken, in quotes, or "(none)".

For example:

```
SCRIPT FOR REVIEW: Create Your First Google Slides Presentation
For: older adults new to computers | About 1:06 | Speaking rate: 150 words/min

1. [TITLE CARD]  0:00-0:04
   On screen: "Create Your First Google Slides Presentation" / "Name your file and add a title"
   Narration: (none)

2. [PRESENTER - on camera]  0:04-0:11
   Narration: "We'll create a presentation, give it a name, and add a title and subtitle."

3. [SCREEN STILL - recording 1 at 0:02]  0:11-0:15
   On screen: arrow pointing at New
   Narration: "In Drive, choose New to begin."

4. [SCREEN - recording 1, 0:02-0:05, slowed to 0.75x]  0:15-0:19
   On screen: arrow and click on New, then on Google Slides
   Narration: "Choose New, then select Google Slides."

5. [SCREEN - recording 2, 0:03-0:08 + presenter in corner]  0:19-0:24  (changed)
   On screen: caption shows "New Presentation" as it's typed
   Narration: "Type a name you'll recognize, then press Enter."

...

12. [PRESENTER - silent]  1:04-1:06
   Narration: (none)

Reply with any changes, for example "make the intro shorter" or "say
'click' instead of 'choose'". Or say "looks good" and I'll build the
video.
```

Notes:
- Times in the cues are planned estimates. The builder lengthens a segment
  if its narration runs long, so the finished video can be a little longer.
  Say this once at the top only if any line is close to its limit.
- Use the recording times from metadata.json in m:ss form (recording 1,
  0:02-0:05), so the user can find the moment in their own recording.
- Keep **On screen** short. The user is checking the story and the words,
  not prop timings.
- Never include passwords or personal details, even in **On screen**.

## Revising an existing timeline

The timeline may have been edited by hand since you last saw it, so treat
the file as the source of truth, not your memory of it. Change what was asked
for and leave everything else as it is.

1. **See where things are:**

   ```bash
   python <skill-dir>/scripts/validate_timeline.py <path/to/timeline.json> --outline
   ```

   This prints each segment's id, type, video time range, source clip,
   props and the start of its script, then any problems. Use it to find what
   the user means ("the part at 0:23", "the second screen clip", "the
   recap"). Then read the JSON of only the segments you'll change.

   If the user describes times in the *built* video, they can be a little
   later than the outline shows: the builder lengthens segments whose
   narration runs long, and prints which ones when it builds.

2. **Load only what the change needs.** Read `references/timeline-format.md`
   if it isn't already in your context. Read `references/directing-guide.md`
   only for restructuring or writing new script. Run `inspect_recordings.py`
   only when you need to see the screen: for new or re-recorded footage, a
   new clip or still, or props on events the timeline doesn't use yet.
   Limit it to what you need with `--recording N` and a small
   `--max-images`. For timing questions alone, `--no-frames` is enough.

3. **Work out the smallest edit that does the job:**
   - **Script changes:** rewrite only the scripts asked about, and keep them
     within their segment's duration (the TTS rules still apply).
   - **Shortening or lengthening:** adjust `duration` on presenter, still
     and title segments. On a `screen_recording`, change `clip_start`,
     `clip_end` or `speed`; `--fix` recomputes its `duration`.
   - **When a clip's `clip_start` or `speed` changes, move its props:** a
     prop tied to an event goes to `(event time - clip_start) / speed`
     (`--fix` moves click ripples itself, and adds arrows and ripples for
     clicks that are newly inside the clip). Drop props whose event is no
     longer inside the clip.
   - **Adding, removing or reordering segments:** edit the list, and let
     `--fix` renumber ids and recompute starts.
   - **Re-recorded footage** (metadata.json changed): check every screen
     segment's `recording_id`, `file_name`, clip range and `event_id`s
     against the new metadata. Event ids and coordinates usually change, so
     redo the props of affected clips from the new events.
   - Don't reformat or reorder the rest of the file, and don't touch
     `notes` or hand edits you weren't asked about.

4. **Confirm script changes before saving.** If the revision changes any
   narration, or adds, removes or reorders segments, plan it first, then
   show the user the whole script in the **Script review** format, with the
   affected segments marked `(changed)`, `(new)` or `(removed)`. Wait for
   approval as in Workflow step 5, and only then edit the timeline. This
   applies even when the user dictated the new wording, so they can see it
   in context.
   Changes that leave every line of narration and the segment list as they
   are (moving an arrow, fixing a zoom, trimming dead time in a clip) don't
   need this: make them directly.

5. **Validate and fix** as in Workflow step 7, delete the screenshots if
   you made any, then **rebuild the video** as in Workflow step 8, so the
   user can watch the change straight away. Skip the rebuild only if they
   asked you not to build.

6. **Report** what changed, segment by segment (before and after, in a line
   each), plus the new total length and where the rebuilt video is. If you
   had to change something the user didn't ask for to keep the timeline
   valid, say what and why. Don't paste the whole JSON.

If the request amounts to a new video (a different topic or audience, or
most segments changing), say so and follow Workflow instead, script review
included, replacing the timeline in place.

## Rules that matter most

- Every screen clip and still must use a real recording: its `id` and
  `file_name` from metadata.json, and times inside its `duration`.
- A `screen_recording`'s `duration` is `(clip_end - clip_start) / speed`.
  Never stretch it to fit a long script. Shorten the script, slow the clip
  down, or add a `screen_still` instead.
- Prop times are relative to the segment, and coordinates are in the
  recording's pixel space. Use the event's `location` exactly for clicks.
- Every click shown in a clip gets an `arrow` and a `click_ripple` tied to
  it by `event_id` (`--fix` adds any you leave out).
- `cartoon_silent` has no script. `cartoon_talking` always has one.
- No timeline.json until the user has approved the script (unless they
  said to skip the review), and no narration in it that they haven't seen
  or won't see in your report.
- Never put passwords, tokens or other secrets in the script or props.
- Leave the recordings folder as you found it plus the timeline, and delete
  the screenshots once the script is written.
- Finish with a built video, not a command for the user to run.
