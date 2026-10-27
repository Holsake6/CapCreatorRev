import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    """Every test gets an isolated data root; nothing touches capcut_local_data/."""
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setenv("CAPCREATOR_DATA", str(root))
    monkeypatch.setenv("CAPCREATOR_CLIP", "off")
    return root


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Tests never reach CapCut: anything not mocked fails like an offline machine."""
    from capcreator import net

    def offline(url, *args, **kwargs):
        raise net.NetError("dns", url, "network disabled in tests")
    monkeypatch.setattr(net, "request", offline)
    monkeypatch.setattr(net, "download", offline)


@pytest.fixture(scope="session")
def videos(tmp_path_factory):
    """A small library of synthetic templates: on-beat fast cuts, off-beat fast cuts, slow dark takes."""
    from synth import make_video
    folder = tmp_path_factory.mktemp("videos")
    out = {}
    for i in range(6):
        out[f"fast{i}"] = make_video(folder / f"fast{i}.mp4", "fast", seed=i, seconds=4)
        out[f"slow{i}"] = make_video(folder / f"slow{i}.mp4", "slow", seed=i, seconds=4)
    for i in range(3):
        out[f"off{i}"] = make_video(folder / f"off{i}.mp4", "fast", seed=50 + i, seconds=4, beat_offset=0.25)
    return out
