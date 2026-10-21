"""Shared settings: output format, asset locations, voice, fonts and colors."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

WIDTH, HEIGHT, FPS = 1920, 1080, 30

KOKORO_MODEL = ASSETS / "tts" / "kokoro" / "kokoro-v1.0.int8.onnx"
KOKORO_VOICES = ASSETS / "tts" / "kokoro" / "voices-v1.0.bin"
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
