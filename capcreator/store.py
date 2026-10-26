"""Small JSON persistence helpers. Writes are atomic so a crash never leaves half a file."""

import json
import os
import tempfile
import threading
from pathlib import Path

# One process-wide lock is enough: the server is the only writer and every
# write is small. It keeps concurrent HTTP handlers from interleaving
# read-modify-write cycles on the same file.
LOCK = threading.RLock()


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return default


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
        os.replace(temp, path)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise
