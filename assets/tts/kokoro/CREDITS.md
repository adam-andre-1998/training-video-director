# Kokoro text-to-speech model

`kokoro-v1.0.int8.onnx` and `voices-v1.0.bin` are the Kokoro-82M v1.0 model
and voice pack, converted to ONNX by the kokoro-onnx project:
https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0

Kokoro is released under the Apache 2.0 license:
https://huggingface.co/hexgrad/Kokoro-82M

For slightly higher quality, download `kokoro-v1.0.onnx` (about 310 MB) from
the same release and put it next to `voices-v1.0.bin`, removing the int8
file (the first of `KOKORO_MODELS` in `video_builder/config.py` that's found
is used).

These files are also looked for in the folder named by the `KOKORO_DIR`
environment variable and in `%LOCALAPPDATA%\training-video-director\kokoro\`.
Without them, the builder uses the built-in Windows voices. The README explains
how to clone the repository without these files where they're blocked.
