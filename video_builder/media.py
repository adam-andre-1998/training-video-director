"""Reading frames from the screen recordings."""

import cv2


class ClipReader:
    """Returns frames of a video by time, reading forward and seeking only when needed."""

    def __init__(self, path):
        self.cap = cv2.VideoCapture(str(path))
        if not self.cap.isOpened():
            raise FileNotFoundError(f"Can't open video {path}")
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30
        self.count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.size = (int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        self.pos = -1
        self.frame = None

    def frame_at(self, t):
        index = min(max(int(round(t * self.fps)), 0), max(self.count - 1, 0))
        if self.frame is None or index < self.pos or index > self.pos + 2 * self.fps:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, index)
            self.pos = index - 1
        while self.pos < index:
            ok, frame = self.cap.read()
            if not ok:
                break  # past the end: keep showing the last frame
            self.frame, self.pos = frame, self.pos + 1
        if self.frame is None:
            raise RuntimeError("Couldn't read any frame")
        return self.frame

    def close(self):
        self.cap.release()
