"""Taste learning: turn examples and clicks into a per-category style model.

This mirrors what Midjourney does for images (personalization / moodboards),
applied to Template DNA:

1. **Moodboard start** – uploaded example videos are positives. Their robust
   centre in feature space plus up to four representative prototypes
   (k-medoids, after Pinterest's PinnerSage) give a usable model from day one.
2. **Keep clicking** – the trainer shows a small grid. Picked templates become
   positives, skipped ones weak negatives, and every pick beats every skip in
   a pairwise (Bradley–Terry) comparison.
3. **Review feedback** – approving / rejecting creators labels their analysed
   templates, weaker because a rejection is not always about style.
4. **Unlabelled background** – everything else crawled for the category is a
   faint negative (positive-unlabelled learning), so features that are merely
   common in CapCut stop counting as "style".

The model is a regularised logistic / Bradley–Terry fit over standardised
features. Its weights are readable, which is what lets the UI say *why* a
template matches. Each retrain gets a short profile code, like an ``--p`` code.
"""

import hashlib
import math
import time

from .dna import FEATURE_INFO, FEATURE_NAMES, PALETTE_BINS, PALETTE_LABELS

AUDIO_FEATURES = {"tempo_bpm", "onset_rate", "audio_energy", "beat_sync", "beat_motion"}
PALETTE_DIMS = PALETTE_BINS + 2
EXTRA = ("proto_sim", "embed_sim")
SOURCE_WEIGHTS = {
    "example": 1.0,      # uploaded / linked example the client says is this category
    "like": 0.8,         # picked in the trainer grid
    "dislike": 0.8,      # explicitly marked "not this" in the trainer
    "skip": 0.25,        # shown in the grid but not picked
    "approved": 0.6,     # template of an approved creator
    "rejected_style": 0.5,
    "rejected_other": 0.12,
    "background": 0.08,  # unlabelled crawl
    "pair": 1.0,
    "grid_pair": 0.5,
}


def _np():
    import numpy as np
    return np


def feature_names():
    return list(FEATURE_NAMES) + [f"palette_{i}" for i in range(PALETTE_DIMS)] + list(EXTRA)


def label_of(name):
    if name in FEATURE_INFO:
        return FEATURE_INFO[name]["label"]
    if name.startswith("palette_"):
        return "色调·" + PALETTE_LABELS[int(name.split("_")[1])]
    return {"proto_sim": "接近代表案例", "embed_sim": "画面内容相似（CLIP）"}.get(name, name)


# ---------------------------------------------------------------- normalisation

def fit_normaliser(records):
    """Robust centre/scale per raw scalar from every analysed template in the pool."""
    np = _np()
    norm = {}
    for name in FEATURE_NAMES:
        values = [r["scalars"][name] for r in records
                  if name in r.get("scalars", {}) and (name not in AUDIO_FEATURES or r.get("has_audio"))]
        if len(values) < 2:
            norm[name] = [values[0] if values else 0.0, 1.0]
            continue
        arr = np.array(values, dtype=float)
        center = float(np.median(arr))
        scale = float(np.percentile(arr, 75) - np.percentile(arr, 25)) / 1.349
        if scale < 1e-6:
            scale = float(arr.std()) or 1.0
        norm[name] = [center, max(scale, 1e-4)]
    palettes = [r["palette"] for r in records if len(r.get("palette") or []) == PALETTE_DIMS]
    norm["_palette_mean"] = [float(x) for x in (np.mean(palettes, axis=0) if palettes else np.zeros(PALETTE_DIMS))]
    return norm


def base_vector(record, norm):
    np = _np()
    scalars = record.get("scalars", {})
    values = []
    for name in FEATURE_NAMES:
        if name not in scalars or (name in AUDIO_FEATURES and not record.get("has_audio")):
            values.append(0.0)  # unknown -> neutral
            continue
        center, scale = norm.get(name, [0.0, 1.0])
        values.append((scalars[name] - center) / scale)
    palette = record.get("palette") or []
    mean = norm.get("_palette_mean") or [0.0] * PALETTE_DIMS
    if len(palette) == PALETTE_DIMS:
        values.extend((p - m) / 0.08 for p, m in zip(palette, mean))
    else:
        values.extend([0.0] * PALETTE_DIMS)
    return np.clip(np.array(values, dtype=float), -3, 3)


def kmedoids(points, k, iters=20):
    """Tiny PAM-style k-medoids returning medoid indices (k <= len(points))."""
    np = _np()
    n = len(points)
    if n == 0:
        return []
    k = max(1, min(k, n))
    dist = np.linalg.norm(points[:, None, :] - points[None, :, :], axis=2)
    medoids = [int(np.argmin(dist.sum(axis=1)))]
    while len(medoids) < k:  # farthest-first initialisation is deterministic
        medoids.append(int(np.argmax(dist[:, medoids].min(axis=1))))
    for _ in range(iters):
        assign = np.argmin(dist[:, medoids], axis=1)
        changed = False
        for c in range(k):
            members = np.where(assign == c)[0]
            if not len(members):
                continue
            best = int(members[np.argmin(dist[np.ix_(members, members)].sum(axis=1))])
            if best != medoids[c]:
                medoids[c] = best
                changed = True
        if not changed:
            break
    return medoids


def _unit(v):
    np = _np()
    v = np.asarray(v, dtype=float)
    return v / (np.linalg.norm(v) + 1e-9)


class Features:
    """Feature matrix builder shared by training and scoring (keeps them consistent)."""

    def __init__(self, norm, prototypes=None, proto_scale=1.0, pos_embed=None, neg_embed=None,
                 embed_center=(0.5, 0.1)):
        self.norm = norm
        self.prototypes = prototypes if prototypes is not None else []
        self.proto_scale = proto_scale
        self.pos_embed = pos_embed
        self.neg_embed = neg_embed
        self.embed_center = embed_center

    def vector(self, record):
        np = _np()
        base = base_vector(record, self.norm)
        proto = 0.0
        if len(self.prototypes):
            d = min(float(np.linalg.norm(base - np.asarray(p))) for p in self.prototypes)
            proto = 2.0 * math.exp(-(d / self.proto_scale) ** 2 / 2) - 1.0  # in [-1, 1]
        emb = 0.0
        if self.pos_embed is not None and record.get("embedding"):
            e = _unit(record["embedding"])
            emb = float(e @ self.pos_embed)
            if self.neg_embed is not None:
                emb -= 0.5 * float(e @ self.neg_embed)
            # CLIP cosines sit in a narrow band: standardise against the pool (median, spread).
            center, spread = self.embed_center
            emb = max(-3.0, min(3.0, (emb - center) / max(spread, 0.02)))
        return np.concatenate([base, [proto * 2.0, emb]])


def _fit_logistic(X, y, w, prior, lam, iters=80):
    """Weighted logistic regression with ridge toward ``prior``.

    Damped Newton with backtracking: plain IRLS diverges on (nearly) separable
    data, which is the normal case with a handful of examples.
    """
    np = _np()
    d = X.shape[1]
    beta = prior.copy()
    reg = np.full(d, lam)
    reg[-1] = 0.05  # the bias is only lightly regularised

    def loss(b):
        z = X @ b
        return float((w * (np.logaddexp(0, z) - y * z)).sum() + 0.5 * (reg * (b - prior) ** 2).sum())

    current = loss(beta)
    for _ in range(iters):
        p = 1 / (1 + np.exp(-np.clip(X @ beta, -30, 30)))
        grad = X.T @ (w * (p - y)) + reg * (beta - prior)
        hess = (X * (w * p * (1 - p))[:, None]).T @ X + np.diag(reg)
        try:
            step = np.linalg.solve(hess, grad)
        except np.linalg.LinAlgError:
            step = grad / (np.abs(np.diag(hess)) + 1)
        t = 1.0
        while t > 1e-4:
            candidate = beta - t * step
            value = loss(candidate)
            if value <= current - 1e-4 * t * float(grad @ step):
                break
            t *= 0.5
        if t <= 1e-4:
            break
        beta, previous = candidate, current
        current = value
        if previous - current < 1e-7:
            break
    return beta


def train(records, points, pairs, slug="cat", previous=None):
    """Fit the category model.

    records: {key: dna_record}; points: [{key, label 0/1, source}]; pairs: [{win, lose, source}].
    Labels whose key has no DNA yet are kept for later and simply skipped here.
    """
    np = _np()
    previous = previous or {}
    pool = list(records.values())
    if not pool:
        return None
    norm = fit_normaliser(pool)
    positives = [p for p in points if p["label"] == 1 and p["key"] in records]
    if not positives:
        return None

    pos_vectors = np.array([base_vector(records[p["key"]], norm) for p in positives])
    examples = [p for p in positives if p.get("source") == "example"] or positives
    ex_vectors = np.array([base_vector(records[p["key"]], norm) for p in examples])
    k = 1 if len(ex_vectors) < 4 else min(4, len(ex_vectors) // 3 + 1)
    medoids = kmedoids(ex_vectors, k)
    prototypes = [ex_vectors[i] for i in medoids]
    spread = np.linalg.norm(ex_vectors - ex_vectors.mean(axis=0), axis=1)
    proto_scale = float(max(1.5, np.median(spread) * 1.5 if len(spread) else 3.0))

    def embed_centroid(items):
        vecs = [_unit(records[p["key"]]["embedding"]) for p in items if records[p["key"]].get("embedding")]
        return _unit(np.mean(vecs, axis=0)) if vecs else None
    negatives_lab = [p for p in points if p["label"] == 0 and p["key"] in records]
    pos_embed, neg_embed = embed_centroid(positives), embed_centroid(negatives_lab)
    embed_center = (0.5, 0.1)
    if pos_embed is not None:
        sims = []
        for record in pool:
            if record.get("embedding"):
                e = _unit(record["embedding"])
                sims.append(float(e @ pos_embed) - (0.5 * float(e @ neg_embed) if neg_embed is not None else 0.0))
        if len(sims) >= 3:
            embed_center = (float(np.median(sims)), float(np.percentile(sims, 75) - np.percentile(sims, 25)) / 1.349)
    features = Features(norm, prototypes, proto_scale, pos_embed, neg_embed, embed_center)

    labelled = {p["key"] for p in points}
    rows, ys, ws, bias = [], [], [], []
    for p in points:
        if p["key"] not in records:
            continue
        rows.append(features.vector(records[p["key"]]))
        ys.append(float(p["label"]))
        ws.append(SOURCE_WEIGHTS.get(p.get("source"), 0.5) * float(p.get("weight", 1.0)))
        bias.append(1.0)
    background = [key for key in records if key not in labelled]
    for key in background:
        rows.append(features.vector(records[key]))
        ys.append(0.0)
        ws.append(SOURCE_WEIGHTS["background"])
        bias.append(1.0)
    n_pairs = 0
    for pair in pairs:
        if pair["win"] in records and pair["lose"] in records:
            rows.append(features.vector(records[pair["win"]]) - features.vector(records[pair["lose"]]))
            ys.append(1.0)
            ws.append(SOURCE_WEIGHTS.get(pair.get("source"), 1.0))
            bias.append(0.0)  # Bradley–Terry: preference depends only on the difference
            n_pairs += 1
    X = np.column_stack([np.array(rows), np.array(bias)])
    y, w = np.array(ys), np.array(ws)

    # Prior direction: "what is consistent in the examples and unusual in the
    # pool". It carries the model while labels are few, then data takes over.
    dims = X.shape[1]
    pos_mean = np.array([features.vector(records[p["key"]]) for p in positives]).mean(axis=0)
    prior = np.zeros(dims)
    consistency = 1 / (1 + pos_vectors.std(axis=0)) if len(pos_vectors) > 1 else np.full(pos_vectors.shape[1], 0.5)
    prior[:pos_vectors.shape[1]] = 0.25 * pos_mean[:pos_vectors.shape[1]] * consistency
    prior[-3] = 0.8  # proto_sim
    # "Looks like the examples" (CLIP) is the most direct content signal there is;
    # verified live: it ranked dog templates above dance ones from 6 dog examples.
    prior[-2] = 1.5 if features.pos_embed is not None else 0.0
    prior[-1] = -0.5
    effective = sum(1 for p in points if p["key"] in records and p.get("source") != "background") + n_pairs
    lam = 2.0 + 30.0 / (1 + effective / 10)
    beta = _fit_logistic(X, y, w, prior, lam)

    names = feature_names()
    weights = {name: round(float(v), 4) for name, v in zip(names, beta[:-1])}
    confidence = 1 - math.exp(-effective / 30)
    revision = int(previous.get("revision", 0)) + 1
    fingerprint = hashlib.sha1(",".join(f"{v:.2f}" for v in beta).encode()).hexdigest()[:6]
    model = {
        "version": 1, "revision": revision,
        # Non-ASCII category names get hash slugs ("c-36454dc9"); "cat" reads better than "c-36".
        "code": f"{'cat' if slug.startswith('c-') else slug[:4]}-v{revision}-{fingerprint}",
        "trained_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "norm": norm, "weights": weights, "bias": round(float(beta[-1]), 4),
        "prototypes": [[round(float(x), 4) for x in p] for p in prototypes],
        "prototype_keys": [examples[i]["key"] for i in medoids],
        "proto_scale": proto_scale,
        "pos_embed": None if features.pos_embed is None else [round(float(x), 5) for x in features.pos_embed],
        "neg_embed": None if features.neg_embed is None else [round(float(x), 5) for x in features.neg_embed],
        "embed_center": [round(x, 5) for x in features.embed_center],
        "counts": {"records": len(records), "positives": len(positives), "negatives": len(negatives_lab),
                   "background": len(background), "pairs": n_pairs,
                   "examples": sum(p.get("source") == "example" for p in positives)},
        "confidence": round(confidence, 3),
    }
    model["explanation"] = explain(model)
    return model


def _features_for(model):
    np = _np()
    return Features(model["norm"], [np.array(p) for p in model.get("prototypes", [])],
                    model.get("proto_scale", 3.0),
                    None if not model.get("pos_embed") else np.array(model["pos_embed"]),
                    None if not model.get("neg_embed") else np.array(model["neg_embed"]),
                    tuple(model.get("embed_center") or (0.5, 0.1)))


def score_records(model, records):
    """{key: probability 0..1} for every DNA record."""
    if not model or not records:
        return {}
    np = _np()
    features = _features_for(model)
    beta = np.array([model["weights"].get(name, 0.0) for name in feature_names()])
    out = {}
    for key, record in records.items():
        z = float(features.vector(record) @ beta + model.get("bias", 0.0))
        out[key] = 1 / (1 + math.exp(-max(-30, min(30, z))))
    return out


def explain(model, top=6):
    """Readable "what this category likes / avoids" from weight × prototype direction."""
    weights = model["weights"]
    items = []
    extra_text = {"proto_sim": "更接近示例里的代表案例", "embed_sim": "画面内容更像示例（CLIP）"}
    for name, value in weights.items():
        if abs(value) < 0.05 or (name in EXTRA and (value < 0.3 or (name == "embed_sim" and not model.get("pos_embed")))):
            continue
        info = FEATURE_INFO.get(name)
        text = extra_text.get(name) or (info["higher"] if info else label_of(name) + "更多")
        items.append({"feature": name, "label": label_of(name), "weight": value, "text": text})
    items.sort(key=lambda item: -abs(item["weight"]))
    likes = [item for item in items if item["weight"] > 0][:top]
    avoids = [item for item in items if item["weight"] < 0][:top]
    return {"likes": likes, "avoids": avoids}


def explain_record(model, record, top=3):
    """Per-template reasons: which features pushed this one up or down the most."""
    if not model or not record:
        return []
    features = _features_for(model)
    vector = features.vector(record)
    names = feature_names()
    contrib = []
    for name, x in zip(names, vector):
        c = model["weights"].get(name, 0.0) * float(x)
        if abs(c) >= 0.15:
            contrib.append((c, name, float(x)))
    contrib.sort(key=lambda item: -abs(item[0]))
    reasons = []
    for c, name, x in contrib[:top]:
        direction = "高" if x > 0 else "低"
        reasons.append({"feature": name, "label": label_of(name), "effect": round(c, 2),
                        "text": f"{label_of(name)}{direction}（{'+' if c > 0 else '−'}）"})
    return reasons


# ---------------------------------------------------------------- active selection

def choose_grid(model, records, candidates, labelled, size=6, rng=None, author_of=None):
    """Pick the next trainer grid: exploit / uncertain / explore, one template per creator.

    ``candidates`` are keys eligible to be shown (they may lack DNA: those are
    used for exploration until analysed).
    """
    import random
    np = _np()
    rng = rng or random.Random()
    author_of = author_of or (lambda key: key)
    pool = [key for key in candidates if key not in labelled]
    if not pool:
        return []
    with_dna = [key for key in pool if key in records]
    scores = score_records(model, {key: records[key] for key in with_dna}) if model else {}
    picked, authors = [], set()

    def take(keys, n):
        added = 0
        for key in keys:
            if added >= n or len(picked) >= size:
                break
            author = author_of(key)
            if key in picked or author in authors:
                continue
            picked.append(key)
            authors.add(author)
            added += 1

    if scores:
        ranked = sorted(scores, key=lambda k: -scores[k])
        take(ranked, max(1, size // 3))                                   # exploit
        take(sorted(scores, key=lambda k: abs(scores[k] - 0.5)), max(1, size // 3))  # uncertain
        if len(picked) < size and model:                                  # explore: far from what was labelled
            features = _features_for(model)
            seen = [features.vector(records[k]) for k in labelled if k in records]
            if seen:
                seen = np.array(seen)
                far = sorted(with_dna, key=lambda k: -float(np.linalg.norm(seen - features.vector(records[k]), axis=1).min()))
                take(far, size - len(picked))
    rest = pool[:]
    rng.shuffle(rest)
    take(rest, size - len(picked))
    rng.shuffle(picked)
    return picked[:size]


def grid_feedback(shown, picked, at=None):
    """Convert one grid round into point labels and implicit pairs."""
    at = at or time.strftime("%Y-%m-%d %H:%M:%S")
    picked = [key for key in picked if key in shown]
    skipped = [key for key in shown if key not in picked]
    points = [{"key": key, "label": 1, "source": "like", "at": at} for key in picked]
    points += [{"key": key, "label": 0, "source": "skip", "at": at} for key in skipped]
    pairs = [{"win": a, "lose": b, "source": "grid_pair", "at": at} for a in picked for b in skipped]
    return points, pairs
