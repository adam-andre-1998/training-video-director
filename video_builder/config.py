"""Shared settings: output format, asset locations, voice, fonts and colors."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
OUTPUT_DIR = ROOT / "output"   # finished videos go here by default
RECORDINGS_DIR = ROOT / "recordings"
TTS_CACHE = ROOT / ".cache" / "tts"   # narration audio reused between builds
TTS_CACHE_DAYS = 30                   # cached narration unused this long is deleted

WIDTH, HEIGHT, FPS = 1920, 1080, 30

# The Kokoro model files are looked for in these folders, in order: a folder
# named by the KOKORO_DIR environment variable, the project's assets, and a
# per-user folder outside the repository (for copies made by hand where the
# files can't be downloaded or pulled). Without them, narration falls back to
# the built-in Windows voices.
KOKORO_DIRS = [Path(p) for p in (os.environ.get("KOKORO_DIR"),) if p] + [
    ASSETS / "tts" / "kokoro",
    Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "training-video-director" / "kokoro",
]
KOKORO_MODELS = ("kokoro-v1.0.int8.onnx", "kokoro-v1.0.onnx")   # first one found is used
KOKORO_VOICES = "voices-v1.0.bin"
KOKORO_DOWNLOAD = "https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0"
KOKORO_VOICE = "af_heart"   # warm US English female voice; see --list-voices
KOKORO_RATE = 180           # Kokoro's natural speaking rate (words per minute) at speed 1.0

FONTS = Path("C:/Windows/Fonts")
FONT_REGULAR = FONTS / "segoeui.ttf"
FONT_BOLD = FONTS / "segoeuib.ttf"
FONT_MONO = FONTS / "consola.ttf"

# Colors are BGR, matching OpenCV frames.
BACKDROP_TOP = (92, 52, 30)       # deep navy
BACKDROP_BOTTOM = (150, 98, 58)   # lighter blue
ACCENT = (26, 122, 255)           # orange: arrows, ripples
HIGHLIGHT = (40, 210, 255)        # yellow: highlight boxes
WHITE = (255, 255, 255)
INK = (48, 38, 34)                # near-black text
CAPTION_BG = (40, 30, 25)

SPEECH_TAIL = 0.3       # seconds of silence kept after narration when a segment is stretched
FADE = 0.5              # fade in from / out to black at the start and end of the video
