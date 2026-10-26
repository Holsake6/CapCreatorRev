import random

from capcreator import dna, taste


def analyse(videos):
    return {key: dna.analyze_video(path, key=key, embed=False) for key, path in videos.items()}


def test_dna_separates_editing_styles(videos):
    records = analyse(videos)
    fast, slow, off = records["fast0"]["scalars"], records["slow0"]["scalars"], records["off0"]["scalars"]
    assert fast["cut_rate"] > 1.0 and slow["cut_rate"] < 0.3
    assert fast["beat_sync"] > 0.6, "cuts placed on the clicks must read as on-beat"
    assert off["beat_sync"] < 0.3, "the same cuts shifted half a beat must not"
    assert fast["saturation"] > slow["saturation"] and fast["brightness"] > slow["brightness"]
    assert records["slow0"]["palette"][dna.PALETTE_BINS] > 0.5  # dark bin dominates
    assert "强卡点" in dna.describe(fast) and "暗调" in dna.describe(slow)


def test_dna_is_cached_by_key(videos):
    first = dna.analyze_video(videos["fast1"], key="tcache", embed=False)
    assert dna.cached("tcache")["scalars"] == first["scalars"]


def test_sync_score_bounds():
    beats = [i * 0.5 for i in range(1, 20)]
    assert dna.sync_score(beats, beats, 10) == 1.0
    assert dna.sync_score([b + 0.25 for b in beats], beats, 10) == 0.0
    assert dna.sync_score([1.0], beats, 10) == 0.0


def test_taste_learns_from_three_examples(videos):
    records = analyse(videos)
    points = [{"key": f"fast{i}", "label": 1, "source": "example"} for i in range(3)]
    model = taste.train(records, points, [], slug="test")
    scores = taste.score_records(model, records)
    assert min(scores[f"fast{i}"] for i in range(3, 6)) > max(scores[f"slow{i}"] for i in range(6))
    assert model["code"].startswith("test-v1-")
    assert model["explanation"]["likes"], "a readable explanation is produced"


def test_pairwise_feedback_moves_ranking(videos):
    records = analyse(videos)
    points = [{"key": f"fast{i}", "label": 1, "source": "example"} for i in range(2)]
    base = taste.score_records(taste.train(records, points, []), records)
    pairs = [{"win": f"fast{i}", "lose": f"off{j}", "source": "pair"} for i in range(2, 6) for j in range(2)]
    tuned = taste.train(records, points, pairs, previous={"revision": 1})
    after = taste.score_records(tuned, records)
    assert tuned["revision"] == 2 and tuned["counts"]["pairs"] == len(pairs)
    # held-out off-beat template drops relative to on-beat ones
    assert after["fast5"] - after["off2"] > base["fast5"] - base["off2"]


def test_no_positive_means_no_model(videos):
    records = analyse({"slow0": videos["slow0"]})
    assert taste.train(records, [], []) is None


def test_grid_is_diverse_and_complete(videos):
    records = analyse(videos)
    model = taste.train(records, [{"key": "fast0", "label": 1, "source": "example"}], [])
    authors = {key: key[:4] for key in records}  # fast*/slow* share an "author"
    grid = taste.choose_grid(model, records, list(records), {"fast0"}, size=2, rng=random.Random(1),
                             author_of=authors.get)
    assert len(grid) == 2 and len({authors[k] for k in grid}) == 2
    grid = taste.choose_grid(model, records, list(records), {"fast0"}, size=6, rng=random.Random(1))
    assert len(grid) == 6 and "fast0" not in grid


def test_grid_feedback_creates_pairs():
    points, pairs = taste.grid_feedback(["a", "b", "c"], ["a"], at="t")
    assert {(p["key"], p["label"]) for p in points} == {("a", 1), ("b", 0), ("c", 0)}
    assert {(p["win"], p["lose"]) for p in pairs} == {("a", "b"), ("a", "c")}
