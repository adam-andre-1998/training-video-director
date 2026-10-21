"""Locating ffmpeg and piping raw frames into it."""

import shutil
import subprocess


def ffmpeg_exe():
    """ffmpeg on PATH, or the copy bundled with the imageio-ffmpeg package."""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
    except ImportError:
        raise SystemExit("ffmpeg not found: install it or run  pip install imageio-ffmpeg")
    return imageio_ffmpeg.get_ffmpeg_exe()


class VideoWriter:
    """Encodes BGR frames to H.264, optionally muxing in an audio file."""

    def __init__(self, path, width, height, fps, audio=None, log_path=None, crf=20):
        cmd = [ffmpeg_exe(), "-y", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}", "-r", str(fps), "-i", "-"]
        if audio:
            cmd += ["-i", str(audio)]
        cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p"]
        if audio:
            cmd += ["-c:a", "aac", "-b:a", "160k", "-shortest"]
        cmd += ["-movflags", "+faststart", str(path)]
        self._log_path = log_path
        self._log = open(log_path, "w") if log_path else subprocess.DEVNULL
        self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=self._log)

    def write(self, frame):
        self._proc.stdin.write(frame.tobytes())

    def close(self):
        self._proc.stdin.close()
        code = self._proc.wait()
        if self._log is not subprocess.DEVNULL:
            self._log.close()
        if code:
            # The log may live in a temporary folder, so put its contents in the error.
            detail = open(self._log_path).read().strip()[-2000:] if self._log_path else ""
            raise RuntimeError(f"ffmpeg exited with code {code}" + (f":\n{detail}" if detail else ""))
