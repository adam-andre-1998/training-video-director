# timeline.json format (version 1)

This file is the contract between the director skill and the video assembler
(the Python + ffmpeg script that builds the final video). Every field here is
something the assembler reads. Don't add fields that aren't listed, except
`notes`, which the assembler ignores.

## Conventions

- **Times are in seconds**, as decimals rounded to 2 places.
- **Segments use `start` + `duration`.** `duration` is what ffmpeg needs
  (`-t`) and what the narration has to fit into. `start` is the segment's
  position in the final video. It always equals the previous segment's
  `start + duration`, so segments never overlap and never leave gaps. The
  first segment starts at `0`.
- **Prop times are relative to the start of their segment**, not the whole
  video. A prop with `"start": 1.5` appears 1.5 s after its segment begins.
- **Prop coordinates are in the source recording's pixels**, the same space
  as the click `location`s in metadata.json (see that recording's
  `resolution`). The assembler maps them onto the laptop screen.
- **Event references**: `event_id` points to an event in the recording that
  the segment's `source.recording_id` names.

## Top level

```json
{
  "version": 1,
  "title": "Creating your first project",
  "summary": "One or two sentences on what the viewer will learn.",
  "audience": "New team members who have never used the tool",
  "metadata_file": "metadata.json",
  "voice": { "words_per_minute": 150 },
  "total_duration": 74.5,
  "segments": [ ... ]
}
```

| field | type | meaning |
|---|---|---|
| `version` | int | Always `1`. |
| `title` | string | Video title. Also used by the opening title card. |
| `summary` | string | Short description of the video. |
| `audience` | string | Who the video is for. Drives the script's tone. |
| `metadata_file` | string | Path to the recordings' metadata.json, relative to timeline.json. |
| `voice.words_per_minute` | number | Speaking rate the script was timed for (default 150). |
| `total_duration` | number | Sum of all segment durations. |
| `segments` | array | The video, in order. |

## Segments

Fields every segment has:

| field | type | meaning |
|---|---|---|
| `id` | int | 1, 2, 3, … in order. |
| `type` | string | One of the types below. |
| `start` | number | Position in the final video. |
| `duration` | number | Length of the segment. |
| `script` | string | Narration spoken during this segment, written for text-to-speech. Use `""` for none. |
| `script_offset` | number | Optional, default `0`. Seconds after the segment starts before narration begins. |
| `flexible` | bool | Optional. If the real TTS audio comes out longer than the segment, the assembler may lengthen a flexible segment to fit (a cartoon loops longer, a still or title card holds longer). Defaults: `true` for `cartoon_talking`, `cartoon_silent`, `screen_still`, `title_card`; `false` for `screen_recording`. |
| `props` | array | Optional overlays (see Props). |
| `notes` | string | Optional director's note for humans. The assembler ignores it. |

### `title_card`

A full-screen text card.

```json
{ "id": 1, "type": "title_card", "start": 0, "duration": 3.5, "script": "",
  "text": { "title": "Creating your first project", "subtitle": "A two-minute walkthrough" } }
```

`text.title` is required and `text.subtitle` is optional.

### `cartoon_talking`

The cartoon presenter, seated at a desk in an office, fills the frame and
talks. Her mouth is synced to the narration and closes when it stops, so
`script` must be non-empty and should fill most of the duration.

### `cartoon_silent`

The presenter fills the frame, animated but not talking. Use it for short
beats: a pause between sections, a moment to read a callout, or the closing
shot. `script` must be `""`.

### `screen_recording`

A clip from a screen recording, shown inside the laptop.

```json
{
  "id": 4, "type": "screen_recording", "start": 18.5, "duration": 9.6,
  "script": "Click New Project in the top left corner.",
  "presenter": "none",
  "source": {
    "recording_id": 1,
    "file_name": "recording_20261021_043351.mp4",
    "clip_start": 2.4,
    "clip_end": 12.0,
    "speed": 1.0
  },
  "props": [ ... ]
}
```

| field | meaning |
|---|---|
| `source.recording_id` | `id` of the recording in metadata.json. |
| `source.file_name` | That recording's `file_name`, copied as-is. |
| `source.clip_start` / `source.clip_end` | The part of the recording to use, in recording seconds. |
| `source.speed` | Playback speed, from 0.5 to 3. `duration` must equal `(clip_end - clip_start) / speed`. |
| `presenter` | Optional: `"none"` (default), `"talking"` or `"silent"`. Shows the cartoon head as a small picture-in-picture in a corner of the frame. |

**Converting event times to segment time.** An event at recording time `t`
appears at `(t - clip_start) / speed` seconds into the segment.

### `screen_still`

A freeze-frame of one moment of a recording, shown inside the laptop. Use it
to explain something before it happens, such as pointing at a button the
viewer is about to click.

```json
{ "id": 3, "type": "screen_still", "start": 12.0, "duration": 6.5,
  "script": "Everything starts from the dashboard. Notice the New Project button up here.",
  "source": { "recording_id": 1, "file_name": "recording_20261021_043351.mp4", "time": 2.3 },
  "props": [ ... ] }
```

`source.time` is the moment to freeze, in recording seconds. It also accepts
`presenter`, like `screen_recording`.

## Props

Props are overlays drawn on a segment. Every prop has `type`, `start` and
`duration` (relative to its segment). Props that take coordinates
(`arrow`, `click_ripple`, `highlight_box`, `zoom`, and `callout` with a
`target`) are only allowed on `screen_recording` and `screen_still`.

### `arrow`

An arrow pointing at a spot on screen.

```json
{ "type": "arrow", "start": 0.8, "duration": 1.6, "target": [212, 148],
  "from": "bottom-right", "label": "New Project", "event_id": 3 }
```

- `target`: the point the arrowhead touches.
- `from`: the side the arrow comes in from. One of `top`, `bottom`, `left`,
  `right`, `top-left`, `top-right`, `bottom-left`, `bottom-right`. Point it
  in from the side with the most empty space, usually towards the center of
  the screen.
- `label`: optional short text (1–3 words) at the arrow's tail.
- `event_id`: optional click event this arrow is for.

### `click_ripple`

A short pulse at the exact moment and spot of a click.

```json
{ "type": "click_ripple", "start": 2.1, "duration": 0.6, "target": [212, 148], "event_id": 3 }
```

### `highlight_box`

A rectangle drawn around an area, everything else slightly dimmed.

```json
{ "type": "highlight_box", "start": 0.5, "duration": 3.0, "box": [180, 120, 260, 60], "label": "Project name" }
```

`box` is `[x, y, width, height]`.

### `zoom`

Smoothly zooms the laptop screen in on a point, holds, and zooms back out.

```json
{ "type": "zoom", "start": 3.0, "duration": 4.0, "center": [640, 400], "scale": 1.8 }
```

`scale` is between 1.2 and 3. Use it when the thing being clicked or typed
into is small.

### `callout`

A speech-bubble or banner with short text.

```json
{ "type": "callout", "start": 1.0, "duration": 3.0, "text": "Names must be unique", "anchor": "top" }
```

Give either `anchor` (`top`, `bottom`, `top-left`, `top-right`,
`bottom-left`, `bottom-right`, `center`) or `target: [x, y]` to point the
bubble at a spot. `target` is only allowed on screen segments. Keep `text`
under about 8 words.

### `key_badge`

Shows a keyboard shortcut as key caps, e.g. `Ctrl` `S`.

```json
{ "type": "key_badge", "start": 4.2, "duration": 1.5, "keys": ["Ctrl", "S"], "event_id": 7 }
```

### `typing_caption`

Shows the text being typed as a large caption, so viewers can read it even
when the field on screen is small.

```json
{ "type": "typing_caption", "start": 5.0, "duration": 3.0, "text": "my-first-project", "event_id": 5 }
```
