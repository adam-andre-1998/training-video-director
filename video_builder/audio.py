"""Mixing the per-segment narration clips into one track."""

import wave

import numpy as np


def read_wav(path):
    """(mono float32 samples in -1..1, sample rate)."""
    with wave.open(str(path), "rb") as w:
        rate, channels, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width != 2:
        raise ValueError(f"{path}: only 16-bit WAV is supported")
    samples = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples, rate


def resample(samples, rate, target):
    if rate == target:
        return samples
    n = int(len(samples) * target / rate)
    return np.interp(np.linspace(0, len(samples) - 1, n), np.arange(len(samples)), samples).astype(np.float32)


def loudness(path, fps, frames):
    """Narration loudness per video frame, 0..1, for lip sync.

    RMS of each frame's slice of audio, scaled so normal speech peaks near 1,
    with quiet noise gated out and a quick attack / slower release so the
    mouth doesn't flicker.
    """
    samples, rate = read_wav(path)
    hop = rate / fps
    rms = np.zeros(frames, np.float32)
    for i in range(frames):
        chunk = samples[int(i * hop):int((i + 1) * hop)]
        if len(chunk):
            rms[i] = np.sqrt(np.mean(chunk ** 2))
    voiced = rms[rms > 1e-3]
    if not len(voiced):
        return rms
    level = np.clip(rms / np.percentile(voiced, 90), 0, 1)
    level[level < 0.12] = 0
    out = np.zeros_like(level)
    prev = 0.0
    for i, v in enumerate(level):
        prev = v if v > prev else prev * 0.55 + v * 0.45
        out[i] = prev
    return out


def activity(level, fps, window=0.6):
    """How much speech is going on around each frame (0..1), smoothed over `window` seconds."""
    n = max(int(window * fps), 1)
    talking = (level > 0.05).astype(np.float32)
    return np.convolve(talking, np.ones(n) / n, mode="same")


def build_narration(placements, total_seconds, out_path, rate=44100):
    """Writes a mono WAV of `total_seconds` with each (start_seconds, wav_path) clip placed at its start."""
    track = np.zeros(int(total_seconds * rate) + 1, np.float32)
    for start, path in placements:
        samples, src_rate = read_wav(path)
        samples = resample(samples, src_rate, rate)
        i = int(start * rate)
        end = min(i + len(samples), len(track))
        track[i:end] += samples[:end - i]
    pcm = (np.clip(track, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(out_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return out_path
