"""Generate small synthetic "templates" with known editing styles for tests."""

import math
import subprocess
import wave
from pathlib import Path

import cv2
import numpy as np

from capcreator import dna


def _write_wav(path, seconds, rate, click_times, tone=220.0, click_gain=0.9):
    t = np.arange(int(seconds * rate)) / rate
    signal = 0.08 * np.sin(2 * math.pi * tone * t)
    for ct in click_times:
        start = int(ct * rate)
        n = int(0.04 * rate)
        if start + n < len(signal):
            env = np.exp(-np.arange(n) / (0.008 * rate))
            noise = np.random.default_rng(int(ct * 1000)).normal(0, 1, n)
            signal[start:start + n] += click_gain * env * noise
    pcm = (np.clip(signal, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(pcm.tobytes())


def make_video(path, style="fast", seconds=8.0, fps=24, size=(180, 320), seed=0, audio=True,
               beat_offset=0.0):
    """style: 'fast' = cut on every beat with saturated colours; 'slow' = dark single shot."""
    rng = np.random.default_rng(seed)
    w, h = size
    path = Path(path)
    silent = path.with_suffix(".silent.mp4")
    writer = cv2.VideoWriter(str(silent), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    beat = 0.5
    beats = [i * beat for i in range(1, int(seconds / beat))]
    colors = [tuple(int(c) for c in rng.integers(0, 255, 3)) for _ in range(len(beats) + 1)]
    for i in range(int(seconds * fps)):
        t = i / fps
        if style == "fast":
            shot = sum(t >= b + beat_offset for b in beats)
            hue = (shot * 37 + seed * 11) % 180
            frame = np.zeros((h, w, 3), np.uint8)
            frame[:] = (hue, 220, 230)
            frame = cv2.cvtColor(frame, cv2.COLOR_HSV2BGR)
            cx = int(w / 2 + 40 * math.sin(t * 6))
            cv2.circle(frame, (cx, h // 2), 30, colors[shot % len(colors)], -1)
            cv2.putText(frame, "POP", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
        else:
            frame = np.zeros((h, w, 3), np.uint8)
            level = 25 + int(10 * math.sin(t))
            frame[:] = (level + 10, level, level)
            x = int((t / seconds) * (w - 40))
            cv2.rectangle(frame, (x, h // 2 - 20), (x + 40, h // 2 + 20), (60, 50, 50), -1)
        writer.write(frame)
    writer.release()
    if not audio:
        silent.replace(path)
        return path
    wav = path.with_suffix(".wav")
    clicks = beats if style == "fast" else [i * 1.7 for i in range(1, int(seconds / 1.7))]
    _write_wav(wav, seconds, 22050, clicks)
    exe = dna.ffmpeg_exe()
    subprocess.run([exe, "-v", "error", "-y", "-i", str(silent), "-i", str(wav), "-c:v", "copy",
                    "-c:a", "aac", "-shortest", str(path)], check=True)
    silent.unlink()
    wav.unlink()
    return path
