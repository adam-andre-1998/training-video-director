# Directing guide

How to turn raw recordings into a training video that is easy to follow.

## Structure

A typical video, in order:

1. **`title_card`** (3–4 s, no script): the video title, plus a subtitle
   that names the outcome ("Set up your first pipeline in 2 minutes").
2. **`cartoon_talking` intro** (8–15 s): who this is for, what they'll be
   able to do by the end, and why it matters. No steps yet.
3. **One block per step** of the task. A step is one meaningful thing the
   viewer does, like "open settings" or "fill in the project details", and
   usually covers 1–4 clicks plus any typing. For each step:
   - Optionally a **`screen_still`** first, to orient the viewer before
     anything moves ("This is the dashboard. The button we need is up
     here."). Use one for the first step and whenever the screen changes a
     lot.
   - A **`screen_recording`** of the step itself, with arrows and ripples.
   - Between larger sections, an optional **`cartoon_talking`** bridge
     (3–6 s: "Now that the project exists, let's invite your team.") or a
     **`cartoon_silent`** beat (1–2 s).
4. **`cartoon_talking` recap** (8–15 s): the 2–4 things to remember, plus
   any tip or common mistake.
5. **`cartoon_silent` outro** (2 s) or a closing **`title_card`**.

Keep the presenter on screen for less than about a third of the total
runtime. The recordings are the lesson.

## Pacing the screen recordings

- **Drop dead time.** Gaps of more than about 3 s with no events (loading,
  hesitating, moving the mouse around) should be trimmed out by splitting
  the clip, or sped up (`speed` 1.5–2.5) when the motion helps the viewer
  follow along. Don't narrate a sped-up stretch in detail.
- **Make room for busy moments.** If several clicks happen within a couple
  of seconds and the narration can't keep up, split the clip and put a
  `screen_still` before it to explain, or slow it down (`speed` 0.75). Don't
  go below 0.5.
- **Leave a beat after each step.** End a clip about 0.5–1 s after the last
  event so the viewer sees the result.
- **Narrate slightly ahead.** Say what's about to happen as it starts ("Click
  Save…"), not after it's done.
- **Use `presenter: "talking"`** on longer screen segments where the
  narration is explaining a concept rather than an action. Otherwise leave it
  at `"none"` so the screen is the focus.

## Props for each action

**For every click** inside a `screen_recording` clip, add:

- an `arrow`: starts about 1.2 s before the click (or at 0 if the clip starts
  later than that), ends about 0.3 s after it, with `target` = the click's
  location and `event_id` set.
- a `click_ripple`: starts exactly at the click, lasts 0.6 s.

Converting times: a click at recording time `t` lands at
`(t - clip_start) / speed` seconds into the segment.

**Typing:**

- Add a `typing_caption` from `start_timestamp` to about 1 s after
  `end_timestamp` (converted to segment time), unless the text is long or
  obvious from the narration.
- Shortcuts appear in typed text as `[ctrl+s]`. Show these with a
  `key_badge` (`["Ctrl", "S"]`) at the moment they're pressed, and say
  them in the script ("press Control S").
- Use a `zoom` (scale 1.5–2) when the field being typed into is small or far
  from the center of the screen.

**Optional extras:**

- `highlight_box` for an area the narration talks about without clicking it.
- `callout` for one short tip, warning or "why".

Restraint matters. At most two pointing props (arrow, highlight box) should
be visible at the same time.

## Writing the script for text-to-speech

The script goes straight into a TTS engine, so write it the way it should
sound:

- Plain sentences only: no markdown, bullets, emoji, brackets or URLs.
- Spell out shortcuts and symbols: "Control S", not "Ctrl+S"; "dot",
  "slash" and "dash" when reading out file names or paths.
- Avoid abbreviations the engine might misread ("e.g.", "i.e.", "etc.").
  Write numbers the way they should be said.
- Short sentences, 8–18 words each. One idea per sentence.
- Talk to the viewer as "you". Be warm and direct, not salesy. No filler like
  "As you can see" or "Simply just".
- Use the names that appear on screen. If a button says "New Project", say
  "New Project".

**Timing.** At the voice's `words_per_minute` (150 means 2.5 words a second),
a segment's script plus `script_offset` must fit inside its `duration`.
Leave about 0.5 s of breathing room at the end of each segment. A
`cartoon_talking` segment should be mostly speech: if the script only fills
half of it, shorten the segment.

## Privacy

Recordings can capture things that shouldn't appear in a training video:

- **Never show or say passwords, tokens or keys.** If typed text was entered
  into a password field, a login screen, or looks like a secret, leave out
  the `typing_caption` and narrate it generically ("enter your password").
- Don't read out personal email addresses, names or customer data from the
  screen unless the user says it's fine. Use generic phrasing instead.
- Window titles in metadata are for your understanding. Don't put them in
  the script unless they're the product name.
