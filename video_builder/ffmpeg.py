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
        if str(path).lower().endswith(".mp4"):
            cmd += ["-movflags", "+faststart"]
        cmd.append(str(path))
        self._log_path = log_path
        self._log = open(log_path, "w") if log_path else subprocess.DEVNULL
        self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=self._log)

    def write(self, frame):
        self._proc.stdin.write(frame.tobytes())

    def close(self):
        self._proc.stdin.close()
        _check(self._proc.wait(), self._log, self._log_path)


def concat(parts, audio, path, work_dir):
    """Joins video-only parts (same size and codec) end to end without re-encoding, adding the audio."""
    list_file = work_dir / "parts.txt"
    list_file.write_text("".join("file '{}'\n".format(str(p).replace("'", "'\\''")) for p in parts),
                         encoding="utf-8")
    cmd = [ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(list_file),
           "-i", str(audio), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
           "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(path)]
    log_path = work_dir / "concat.log"
    log = open(log_path, "w")
    _check(subprocess.call(cmd, stderr=log), log, log_path)


def _check(code, log, log_path):
    if log is not subprocess.DEVNULL:
        log.close()
    if code:
        # The log may live in a temporary folder, so put its contents in the error.
        detail = open(log_path).read().strip()[-2000:] if log_path else ""
        raise RuntimeError(f"ffmpeg exited with code {code}" + (f":\n{detail}" if detail else ""))
