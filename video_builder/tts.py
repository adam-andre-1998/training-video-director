"""Text-to-speech.

Two engines, behind one function, `synthesize`:

- "kokoro" (default): the Kokoro neural voice model, run locally with
  kokoro-onnx. Natural-sounding, offline. Model files live in assets/tts/kokoro/.
- "windows": the built-in Windows (SAPI5) voices via pyttsx3, as a fallback.
"""

import hashlib
import json
import os
import time
import wave
from pathlib import Path

import numpy as np

from .config import KOKORO_MODEL, KOKORO_RATE, KOKORO_VOICE, KOKORO_VOICES, TTS_CACHE_DAYS

ENGINES = ("kokoro", "windows")


def synthesize(scripts, out_dir, words_per_minute=150, voice=None, engine="kokoro", cache_dir=None):
    """Writes one WAV per non-empty script.

    scripts: {segment_id: text}. Returns ({segment_id: (wav_path, seconds)}, number reused).
    With cache_dir, each line's audio is kept there under a hash of its text,
    voice and rate, so rebuilding after a small change only speaks the lines
    that changed.
    """
    if engine not in ENGINES:
        raise ValueError(f"Unknown TTS engine {engine!r} (use 'kokoro' or 'windows')")
    folder = Path(cache_dir or out_dir)
    folder.mkdir(parents=True, exist_ok=True)
    jobs = {}
    for seg_id, text in scripts.items():
        if not text.strip():
            continue
        text = clean(text)
        if cache_dir:
            resolved = voice or (KOKORO_VOICE if engine == "kokoro" else "default")
            key = json.dumps([engine, resolved, words_per_minute, text], ensure_ascii=False)
            name = hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]
        else:
            name = f"segment_{seg_id:03d}"
        jobs[seg_id] = (text, folder / f"{name}.wav")

    # One job per audio file: segments with the same line share it.
    todo = {}
    for seg_id, (text, path) in jobs.items():
        if not (path.exists() and path.stat().st_size) and path not in todo:
            todo[path] = (seg_id, text)
    if todo:
        speak = {seg_id: (text, path.with_suffix(".tmp.wav")) for path, (seg_id, text) in todo.items()}
        (_kokoro if engine == "kokoro" else _windows)(speak, words_per_minute, voice)
        for seg_id, (_, tmp) in speak.items():
            if not tmp.exists() or tmp.stat().st_size == 0:
                raise RuntimeError(f"Text-to-speech produced no audio for segment {seg_id}")
            os.replace(tmp, jobs[seg_id][1])  # only finished files ever get a cache name

    results = {}
    for seg_id, (_, path) in jobs.items():
        if cache_dir:
            os.utime(path)  # recently used: keep it when pruning
        results[seg_id] = (path, wav_duration(path))
    if cache_dir:
        prune(folder)
    return results, len({path for _, path in jobs.values()} - set(todo))


def prune(cache_dir, days=TTS_CACHE_DAYS):
    """Deletes cached narration that no build has used for `days` days."""
    cutoff = time.time() - days * 86400
    for path in Path(cache_dir).glob("*.wav"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass


def clean(text):
    """Normalizes typography that some engines read badly."""
    for a, b in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'), ("—", ", "), ("–", "-")):
        text = text.replace(a, b)
    return " ".join(text.split())


def list_voices(engine="kokoro"):
    if engine == "kokoro":
        return _kokoro_model().get_voices()
    import pyttsx3
    return [v.name for v in pyttsx3.init().getProperty("voices")]


def wav_duration(path):
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def write_wav(path, samples, rate):
    pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


# ------------------------------------------------------------------- kokoro
def _kokoro_model():
    from kokoro_onnx import Kokoro
    for f in (KOKORO_MODEL, KOKORO_VOICES):
        if not f.exists():
            raise SystemExit(f"Missing {f}. Download it from "
                             "https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0")
    return Kokoro(str(KOKORO_MODEL), str(KOKORO_VOICES))


def _kokoro(jobs, words_per_minute, voice):
    model = _kokoro_model()
    voice = voice or KOKORO_VOICE
    if voice not in model.get_voices():
        raise ValueError(f"No Kokoro voice {voice!r}. Voices: {', '.join(model.get_voices())}")
    # Kokoro speaks at about KOKORO_RATE words per minute at speed 1.0.
    speed = min(max(words_per_minute / KOKORO_RATE, 0.6), 1.4)
    for text, path in jobs.values():
        samples, rate = model.create(text, voice=voice, speed=speed, lang="en-us")
        write_wav(path, samples, rate)


# ------------------------------------------------------------------ windows
def _windows(jobs, words_per_minute, voice):
    import pyttsx3
    engine = pyttsx3.init()
    engine.setProperty("rate", int(words_per_minute))
    if voice:
        match = next((v for v in engine.getProperty("voices") if voice.lower() in v.name.lower()), None)
        if match is None:
            names = ", ".join(v.name for v in engine.getProperty("voices"))
            raise ValueError(f"No voice matching {voice!r}. Installed voices: {names}")
        engine.setProperty("voice", match.id)
    for text, path in jobs.values():
        path.unlink(missing_ok=True)
        engine.save_to_file(text, str(path))
    engine.runAndWait()
    engine.stop()
