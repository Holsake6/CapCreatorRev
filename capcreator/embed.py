"""Optional semantic channel: CLIP image embeddings averaged over sampled frames.

Template DNA describes *how* a video is edited; CLIP adds *what* is on screen
(school uniform, night street, pastel stickers ...). It is optional because the
model needs PyTorch and a ~350 MB weight download. Install with
``pip install open_clip_torch torch`` and it is picked up automatically.
Set ``CAPCREATOR_CLIP=off`` to disable it.
"""

import os
import threading

MODEL = os.environ.get("CAPCREATOR_CLIP_MODEL", "ViT-B-32")
PRETRAINED = os.environ.get("CAPCREATOR_CLIP_WEIGHTS", "laion2b_s34b_b79k")
_state = {"loaded": False, "model": None, "preprocess": None, "error": None}
_lock = threading.Lock()


def model_name():
    return f"open_clip:{MODEL}:{PRETRAINED}"


def _load():
    with _lock:
        if _state["loaded"]:
            return _state["model"]
        _state["loaded"] = True
        if os.environ.get("CAPCREATOR_CLIP", "").lower() in ("off", "0", "false"):
            return None
        try:
            import open_clip
            import torch  # noqa: F401  (fail early if PyTorch is missing)
            model, _, preprocess = open_clip.create_model_and_transforms(MODEL, pretrained=PRETRAINED)
            model.eval()
            _state.update(model=model, preprocess=preprocess)
        except Exception as exc:  # missing package, no network for weights, ...
            _state["error"] = str(exc)
        return _state["model"]


def status():
    return {"model": model_name(), "enabled": _load() is not None, "error": _state["error"]}


def embed_frames(frames, limit=8):
    """Mean L2-normalised embedding for BGR uint8 frames, or ``None`` if CLIP is unavailable."""
    model = _load()
    if model is None or not frames:
        return None
    import numpy as np
    import torch
    from PIL import Image
    step = max(1, len(frames) // limit)
    picked = frames[::step][:limit]
    batch = torch.stack([_state["preprocess"](Image.fromarray(f[..., ::-1].copy())) for f in picked])
    with torch.no_grad():
        vectors = model.encode_image(batch).float().numpy()
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-8
    mean = vectors.mean(axis=0)
    mean /= np.linalg.norm(mean) + 1e-8
    return [round(float(x), 5) for x in mean]
