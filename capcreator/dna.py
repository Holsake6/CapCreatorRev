"""Template DNA: a compact, interpretable description of how a video template is made.

A CapCut template is mostly *editing*, not content: the creator's style is in
the cut rhythm, how hard edits land on the beat, the colour treatment, the
packaging layered over the footage and how the subject is framed. Each feature
below measures one of those, so the learned taste can be explained back to the
reviewer ("更快的卡点", "更高饱和度", "人物更近") instead of being a black box.

Requires ``numpy`` and ``opencv-python-headless``. Audio features additionally
need an ffmpeg binary (``imageio-ffmpeg`` ships one); without it they are left
empty and the learner ignores them.
"""

import hashlib
import math
import shutil
import subprocess
import time
from pathlib import Path

from . import paths, store

FEATURE_VERSION = 3
ANALYZE_SECONDS = 60
SAMPLE_FPS = 6
EVENT_TOLERANCE = 0.09  # seconds; a visual hit within 90 ms of an onset counts as "on beat"

# name, group, Chinese label, how to read a higher value
FEATURES = (
    ("duration", "结构", "时长", "更长"),
    ("vertical", "结构", "竖屏", "竖屏"),
    ("cut_rate", "节奏", "切镜频率", "切镜更频繁"),
    ("shot_len_cv", "节奏", "镜头时长变化", "镜头长短变化更大"),
    ("hit_rate", "节奏", "画面冲击点密度", "冲击点（切镜/闪光/大动作）更密"),
    ("beat_sync", "节奏", "卡点同步度", "画面变化更贴合音乐重拍"),
    ("motion_mean", "运动", "画面运动强度", "画面动得更多"),
    ("motion_std", "运动", "运动起伏", "运动强弱对比更大"),
    ("flash_rate", "包装", "闪白/闪光", "闪光特效更多"),
    ("edge_density", "包装", "画面元素密度", "画面元素（文字/贴纸/细节）更多"),
    ("static_overlay", "包装", "固定图形占比", "固定文字/边框/贴纸更多"),
    ("border_ratio", "版式", "边框留白", "边框/留白更多"),
    ("split_layout", "版式", "分屏拼贴", "更多分屏/拼贴版式"),
    ("brightness", "色彩", "亮度", "更明亮"),
    ("contrast", "色彩", "对比度", "对比更强"),
    ("saturation", "色彩", "饱和度", "颜色更鲜艳"),
    ("colorfulness", "色彩", "色彩丰富度", "颜色种类更多"),
    ("warmth", "色彩", "暖色倾向", "更偏暖色"),
    ("sharpness", "画质", "清晰度", "更锐利"),
    ("face_ratio", "主体", "人脸出现率", "更常出现人脸"),
    ("face_size", "主体", "人脸大小", "更近景/大头"),
    ("person_ratio", "主体", "人物出现率", "更常出现人物"),
    ("center_focus", "主体", "主体居中", "动作更集中在画面中央"),
    ("tempo_bpm", "音乐", "音乐速度", "音乐更快"),
    ("onset_rate", "音乐", "音乐重音密度", "鼓点更密"),
    ("audio_energy", "音乐", "音乐响度", "音乐更响"),
)
FEATURE_NAMES = tuple(item[0] for item in FEATURES)
FEATURE_INFO = {item[0]: {"group": item[1], "label": item[2], "higher": item[3]} for item in FEATURES}
PALETTE_BINS = 12  # hue bins; plus "dark" and "light neutral" bins
PALETTE_LABELS = ("红", "橙", "黄", "黄绿", "绿", "青绿", "青", "天蓝", "蓝", "紫", "品红", "粉红", "暗色", "浅色")


class DependencyMissing(RuntimeError):
    pass


def _cv():
    try:
        import cv2
        import numpy as np
    except ImportError as exc:  # pragma: no cover - exercised only without deps
        raise DependencyMissing("视频分析需要 numpy 和 opencv-python-headless：请双击 安装依赖.command") from exc
    return cv2, np


def available():
    try:
        _cv()
        return True
    except DependencyMissing:
        return False


def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


# ---------------------------------------------------------------- audio

def audio_track(path, seconds=ANALYZE_SECONDS, rate=11025):
    """Mono float32 samples, or ``None`` when there is no audio / no ffmpeg."""
    _, np = _cv()
    exe = ffmpeg_exe()
    if not exe:
        return None, rate
    try:
        result = subprocess.run(
            [exe, "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(rate),
             "-t", str(seconds), "-f", "s16le", "-"],
            capture_output=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        return None, rate
    if result.returncode != 0 or len(result.stdout) < rate:  # < 0.5 s of audio
        return None, rate
    samples = np.frombuffer(result.stdout, dtype=np.int16).astype(np.float32) / 32768.0
    return samples, rate


def onset_envelope(samples, rate, hop=256, size=1024):
    """Spectral-flux onset strength at ``rate / hop`` frames per second."""
    _, np = _cv()
    if samples is None or len(samples) < size * 2:
        return None, 0
    frames = 1 + (len(samples) - size) // hop
    index = np.arange(size)[None, :] + hop * np.arange(frames)[:, None]
    window = np.hanning(size).astype(np.float32)
    spectrum = np.abs(np.fft.rfft(samples[index] * window, axis=1))
    log_spec = np.log1p(spectrum * 10)
    flux = np.maximum(0, np.diff(log_spec, axis=0)).sum(axis=1)
    flux = np.concatenate([[0.0], flux])
    if flux.max() > 0:
        flux = flux / flux.max()
    return flux.astype(np.float32), rate / hop


def peak_times(series, fps, min_gap=0.12, rel=0.35, floor=None):
    """Local maxima above an adaptive threshold, as times in seconds."""
    _, np = _cv()
    if series is None or len(series) < 3:
        return []
    series = np.asarray(series, dtype=np.float32)
    median = float(np.median(series))
    mad = float(np.median(np.abs(series - median))) + 1e-6
    threshold = max(median + 3.0 * mad, rel * float(series.max()))
    if floor is not None:
        threshold = max(threshold, floor)
    gap = max(1, int(round(min_gap * fps)))
    peaks, last = [], -gap
    for i in range(1, len(series) - 1):
        if series[i] >= threshold and series[i] >= series[i - 1] and series[i] >= series[i + 1]:
            if i - last >= gap:
                peaks.append(i / fps)
                last = i
            elif series[i] > series[int(round(peaks[-1] * fps))]:
                peaks[-1] = i / fps
                last = i
    return peaks


def tempo_bpm(envelope, fps):
    _, np = _cv()
    if envelope is None or len(envelope) < fps * 4:
        return 0.0
    env = envelope - envelope.mean()
    corr = np.correlate(env, env, mode="full")[len(env) - 1:]
    lo, hi = int(fps * 60 / 200), int(fps * 60 / 60)
    if hi >= len(corr) or lo < 1:
        return 0.0
    lags = np.arange(lo, hi + 1)
    # Mild preference for 90–150 BPM resolves the usual half/double ambiguity.
    bpms = 60 * fps / lags
    weight = np.exp(-0.5 * (np.log2(bpms / 120.0) / 0.9) ** 2)
    best = lags[int(np.argmax(corr[lo:hi + 1] * weight))]
    return float(60 * fps / best)


def sync_score(visual_events, audio_events, duration, tolerance=EVENT_TOLERANCE):
    """How much more often visual hits land on audio onsets than chance would predict.

    0 = no better than random placement, 1 = every hit is on an onset.
    """
    if len(visual_events) < 2 or len(audio_events) < 2 or duration <= 0:
        return 0.0
    audio_sorted = sorted(audio_events)
    import bisect
    hits = 0
    for t in visual_events:
        i = bisect.bisect_left(audio_sorted, t)
        near = min(abs(t - audio_sorted[j]) for j in (i - 1, i) if 0 <= j < len(audio_sorted))
        hits += near <= tolerance
    hit_rate = hits / len(visual_events)
    chance = min(0.95, len(audio_sorted) * 2 * tolerance / duration)
    return float(max(0.0, min(1.0, (hit_rate - chance) / (1 - chance))))


# ---------------------------------------------------------------- video

def _cascade(cv2, name):
    # OpenCV 5 moved Haar cascades out of the main package; faces are then skipped.
    if not hasattr(cv2, "CascadeClassifier") or not hasattr(cv2, "data"):
        return None
    cascade = cv2.CascadeClassifier(str(Path(cv2.data.haarcascades) / name))
    return None if cascade.empty() else cascade


def _people_detector(cv2):
    if not hasattr(cv2, "HOGDescriptor"):
        return None
    hog = cv2.HOGDescriptor()
    hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())
    return hog


def read_frames(path, seconds=ANALYZE_SECONDS, sample_fps=SAMPLE_FPS, width=192, tiny=48):
    """Decode once: a full-rate tiny-gray change series plus sampled colour frames."""
    cv2, np = _cv()
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError("无法打开视频文件")
    fps = cap.get(cv2.CAP_PROP_FPS) or 0
    if not 1 <= fps <= 240:
        fps = 30.0
    step = max(1, int(round(fps / sample_fps)))
    sampled, change, brightness_series = [], [], []
    prev_tiny = None
    index = 0
    limit = int(seconds * fps)
    while index < limit:
        ok, frame = cap.read()
        if not ok:
            break
        h, w = frame.shape[:2]
        small = cv2.resize(frame, (tiny, max(1, int(tiny * h / w))), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32)
        brightness_series.append(float(gray.mean()))
        change.append(0.0 if prev_tiny is None else float(np.abs(gray - prev_tiny).mean()) / 255.0)
        prev_tiny = gray
        if index % step == 0:
            scale = width / w
            sampled.append(cv2.resize(frame, (width, max(1, int(h * scale))), interpolation=cv2.INTER_AREA))
        index += 1
    cap.release()
    if not sampled:
        raise ValueError("视频没有可读取的画面")
    return {"fps": fps, "frames": index, "duration": index / fps, "sample_step": step,
            "sampled": sampled, "change": np.array(change, dtype=np.float32),
            "brightness": np.array(brightness_series, dtype=np.float32), "shape": (h, w)}


def _hist(cv2, hsv):
    hist = cv2.calcHist([hsv], [0, 1, 2], None, [12, 4, 4], [0, 180, 0, 256, 0, 256])
    return cv2.normalize(hist, hist).flatten()


def analyze_frames(decoded, audio=None):
    cv2, np = _cv()
    fps = decoded["fps"]
    duration = max(0.1, decoded["duration"])
    frames = decoded["sampled"]
    sample_fps = fps / decoded["sample_step"]
    h, w = decoded["shape"]

    hsv_frames = [cv2.cvtColor(f, cv2.COLOR_BGR2HSV) for f in frames]
    grays = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames]

    # --- shots: colour-histogram jumps between sampled frames
    hist_dist = [0.0]
    hists = [_hist(cv2, hsv) for hsv in hsv_frames]
    for a, b in zip(hists, hists[1:]):
        hist_dist.append(float(cv2.compareHist(a, b, cv2.HISTCMP_BHATTACHARYYA)))
    hist_dist = np.array(hist_dist, dtype=np.float32)
    cut_threshold = max(0.33, float(np.median(hist_dist) + 4 * np.median(np.abs(hist_dist - np.median(hist_dist)))))
    # Near-black frames make hue histograms jumpy, so a cut also needs a real
    # pixel-level change between the two sampled frames.
    pixel_jump = [0.0] + [float(np.abs(a.astype(np.float32) - b.astype(np.float32)).mean()) / 255
                          for a, b in zip(frames, frames[1:])]
    cut_idx = [i for i in range(1, len(hist_dist))
               if hist_dist[i] >= cut_threshold and pixel_jump[i] >= 0.05]
    bounds = [0, *cut_idx, len(frames)]
    shot_lengths = np.array([(b - a) / sample_fps for a, b in zip(bounds, bounds[1:]) if b > a], dtype=np.float32)
    cut_rate = len(cut_idx) / duration
    shot_len_cv = float(shot_lengths.std() / shot_lengths.mean()) if len(shot_lengths) > 1 else 0.0

    # --- full-rate visual change: motion and "hits"
    change = decoded["change"]
    motion_mean = float(change.mean()) if len(change) else 0.0
    motion_std = float(change.std()) if len(change) else 0.0
    visual_events = peak_times(change, fps, min_gap=0.15, rel=0.3, floor=0.04)
    hit_rate = len(visual_events) / duration
    bright = decoded["brightness"]
    flashes = 0
    if len(bright) > 2:
        jump = np.diff(bright)
        flashes = len(peak_times(np.maximum(0, jump), fps, min_gap=0.2, rel=0.5, floor=35.0))
    flash_rate = flashes / duration

    # --- colour / look
    sat = np.array([hsv[..., 1].mean() / 255 for hsv in hsv_frames])
    val = np.array([hsv[..., 2].mean() / 255 for hsv in hsv_frames])
    contrast = np.array([g.std() / 128 for g in grays])
    colorful, warm = [], []
    palette = np.zeros(PALETTE_BINS + 2, dtype=np.float64)
    for frame, hsv in zip(frames, hsv_frames):
        b, g, r = [c.astype(np.float32) for c in cv2.split(frame)]
        rg, yb = r - g, 0.5 * (r + g) - b
        colorful.append((math.hypot(rg.std(), yb.std()) + 0.3 * math.hypot(rg.mean(), yb.mean())) / 255)
        warm.append(float((r - b).mean()) / 255)
        hue, s, v = hsv[..., 0], hsv[..., 1] / 255.0, hsv[..., 2] / 255.0
        chroma = (s > 0.25) & (v > 0.2)
        bins = (hue[chroma].astype(np.int32) * PALETTE_BINS // 180).clip(0, PALETTE_BINS - 1)
        palette[:PALETTE_BINS] += np.bincount(bins, weights=s[chroma], minlength=PALETTE_BINS)
        palette[PALETTE_BINS] += float((v < 0.2).sum())
        palette[PALETTE_BINS + 1] += float(((s <= 0.25) & (v >= 0.75)).sum()) * 0.5
    palette = palette / palette.sum() if palette.sum() > 0 else palette

    sharp = [math.log1p(cv2.Laplacian(g, cv2.CV_32F).var()) / 10 for g in grays]

    # --- packaging & layout
    edges = [cv2.Canny(g, 80, 180) > 0 for g in grays]
    edge_density = float(np.mean([e.mean() for e in edges]))
    stack = np.stack(edges).astype(np.float32)
    persistence = stack.mean(axis=0)
    static_overlay = float((persistence >= 0.7).mean() / (edge_density + 1e-3)) if edge_density > 0 else 0.0
    static_overlay = min(1.0, static_overlay)

    gray_stack = np.stack(grays).astype(np.float32)
    temporal_std = gray_stack.std(axis=0)
    spatial_std_rows = gray_stack.mean(axis=0).std(axis=1)
    spatial_std_cols = gray_stack.mean(axis=0).std(axis=0)
    still_rows = (temporal_std.mean(axis=1) < 4) & (spatial_std_rows < 6)
    still_cols = (temporal_std.mean(axis=0) < 4) & (spatial_std_cols < 6)

    def edge_run(mask):
        run = 0
        for value in mask:
            if not value:
                break
            run += 1
        return run
    border_ratio = (edge_run(still_rows) + edge_run(still_rows[::-1])) / len(still_rows) + \
                   (edge_run(still_cols) + edge_run(still_cols[::-1])) / len(still_cols)
    border_ratio = float(min(1.0, border_ratio))

    # A split-screen / collage seam is a straight line spanning most of the
    # frame that stays put while the content around it changes.
    def seam_strength(axis):
        coverage = []
        for g in grays:
            grad = np.abs(cv2.Sobel(g, cv2.CV_32F, 1 if axis == 0 else 0, 0 if axis == 0 else 1, ksize=3))
            strong = grad > 60
            coverage.append(strong.mean(axis=axis))  # per column (axis=0) or per row (axis=1)
        mean_cov = np.mean(coverage, axis=0)
        n = len(mean_cov)
        inner = mean_cov[int(n * 0.12):int(n * 0.88)]
        return float(min(1.0, max(0.0, (inner.max() - 0.45) / 0.45))) if len(inner) else 0.0
    split_layout = max(seam_strength(0), seam_strength(1))

    # --- subject
    face_cascade = _cascade(cv2, "haarcascade_frontalface_default.xml")
    hog = _people_detector(cv2)
    face_frames, face_sizes, person_frames, checked = 0, [], 0, 0
    probe_idx = np.linspace(0, len(frames) - 1, num=min(12, len(frames))).astype(int)
    for i in sorted(set(probe_idx.tolist())):
        checked += 1
        big = cv2.resize(frames[i], (320, max(1, int(320 * frames[i].shape[0] / frames[i].shape[1]))))
        gray = cv2.equalizeHist(cv2.cvtColor(big, cv2.COLOR_BGR2GRAY))
        faces = face_cascade.detectMultiScale(gray, 1.15, 5, minSize=(18, 18)) if face_cascade is not None else ()
        person = len(faces) > 0
        if len(faces):
            face_frames += 1
            area = max(fw * fh for (_, _, fw, fh) in faces) / float(gray.shape[0] * gray.shape[1])
            face_sizes.append(math.sqrt(area))
        if not person and hog is not None:
            rects, weights = hog.detectMultiScale(big, winStride=(8, 8), padding=(8, 8), scale=1.08)
            person = len(rects) > 0 and float(np.max(weights)) >= 0.7
        person_frames += person
    face_ratio = face_frames / max(1, checked)
    person_ratio = person_frames / max(1, checked)
    face_size = float(np.mean(face_sizes)) if face_sizes else 0.0

    motion_map = np.abs(np.diff(gray_stack, axis=0)).mean(axis=0) if len(gray_stack) > 1 else temporal_std
    total = motion_map.sum()
    if total > 0:
        ys, xs = np.mgrid[0:motion_map.shape[0], 0:motion_map.shape[1]]
        cy = (motion_map * ys).sum() / total / motion_map.shape[0]
        cx = (motion_map * xs).sum() / total / motion_map.shape[1]
        center_focus = float(max(0.0, 1 - 2 * math.hypot(cx - 0.5, cy - 0.5)))
    else:
        center_focus = 0.0

    # --- audio
    tempo = onset_rate = energy = 0.0
    beat = 0.0
    has_audio = False
    if audio is not None and audio[0] is not None:
        samples, rate = audio
        envelope, env_fps = onset_envelope(samples, rate)
        if envelope is not None:
            has_audio = True
            audio_events = peak_times(envelope, env_fps, min_gap=0.1, rel=0.3)
            onset_rate = len(audio_events) / max(0.1, len(samples) / rate)
            tempo = tempo_bpm(envelope, env_fps)
            energy = float(min(1.0, max(0.0, (20 * math.log10(float(np.sqrt((samples ** 2).mean())) + 1e-6) + 50) / 50)))
            cut_times = [i / sample_fps for i in cut_idx]
            events = sorted(set(round(t, 2) for t in visual_events + cut_times))
            beat = sync_score(events, audio_events, min(duration, len(samples) / rate))

    scalars = {
        "duration": round(duration, 2), "vertical": float(h > w),
        "cut_rate": cut_rate, "shot_len_cv": shot_len_cv, "hit_rate": hit_rate, "beat_sync": beat,
        "motion_mean": motion_mean, "motion_std": motion_std, "flash_rate": flash_rate,
        "edge_density": edge_density, "static_overlay": static_overlay,
        "border_ratio": border_ratio, "split_layout": split_layout,
        "brightness": float(val.mean()), "contrast": float(contrast.mean()), "saturation": float(sat.mean()),
        "colorfulness": float(np.mean(colorful)), "warmth": float(np.mean(warm)), "sharpness": float(np.mean(sharp)),
        "face_ratio": face_ratio, "face_size": face_size, "person_ratio": person_ratio,
        "center_focus": center_focus,
        "tempo_bpm": tempo, "onset_rate": onset_rate, "audio_energy": energy,
    }
    scalars = {key: round(float(value), 4) for key, value in scalars.items()}
    return {"version": FEATURE_VERSION, "scalars": scalars, "has_audio": has_audio,
            "palette": [round(float(x), 4) for x in palette],
            "shots": int(len(shot_lengths)), "sampled_frames": len(frames)}


def file_key(path):
    digest = hashlib.sha1()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return "f" + digest.hexdigest()[:20]


def feature_path(key):
    return paths.features_dir() / f"{key}.json"


def cached(key):
    data = store.read_json(feature_path(key), None)
    return data if data and data.get("version") == FEATURE_VERSION else None


def analyze_video(path, key=None, meta=None, embed=True):
    """Full Template DNA for a local video file, cached by ``key`` (default: content hash)."""
    key = key or file_key(path)
    previous = cached(key)
    if previous:
        return previous
    decoded = read_frames(path)
    result = analyze_frames(decoded, audio_track(path))
    if embed:
        try:
            from . import embed as embedding
            vector = embedding.embed_frames(decoded["sampled"])
            if vector is not None:
                result["embedding"] = vector
                result["embedding_model"] = embedding.model_name()
        except Exception:
            pass
    result.update(key=key, analyzed_at=time.strftime("%Y-%m-%d %H:%M:%S"), meta=meta or {})
    store.write_json(feature_path(key), result)
    return result


def analyze_template(template_id, video_url, meta=None, keep_video=False):
    """Download a CapCut preview, extract DNA, then delete the video unless asked to keep it."""
    key = f"t{template_id}"
    previous = cached(key)
    if previous:
        return previous
    from . import capcut
    video = capcut.download_preview(template_id, video_url)
    try:
        return analyze_video(video, key=key, meta={"template_id": str(template_id), **(meta or {})})
    finally:
        if not keep_video:
            Path(video).unlink(missing_ok=True)


def describe(scalars):
    """Short Chinese reading of the most distinctive raw features (for UI tooltips)."""
    parts = []
    if scalars.get("beat_sync", 0) >= 0.35:
        parts.append("强卡点")
    if scalars.get("cut_rate", 0) >= 1.2:
        parts.append("快切")
    elif scalars.get("cut_rate", 0) <= 0.15:
        parts.append("长镜头")
    if scalars.get("person_ratio", 0) >= 0.6:
        parts.append("人物为主")
    if scalars.get("face_size", 0) >= 0.25:
        parts.append("近景")
    if scalars.get("saturation", 0) >= 0.45:
        parts.append("高饱和")
    if scalars.get("brightness", 0) <= 0.3:
        parts.append("暗调")
    if scalars.get("flash_rate", 0) >= 0.3:
        parts.append("闪光特效")
    if scalars.get("split_layout", 0) >= 0.4:
        parts.append("分屏/拼贴")
    if scalars.get("static_overlay", 0) >= 0.35:
        parts.append("固定包装")
    return parts
