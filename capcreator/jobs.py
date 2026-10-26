"""Background jobs (scan, import, video analysis) with a log the UI can poll."""

import itertools
import threading
import time
import traceback

_jobs = {}
_lock = threading.Lock()
_ids = itertools.count(1)


class Job:
    def __init__(self, kind, slug, title):
        self.id = str(next(_ids))
        self.kind, self.slug, self.title = kind, slug, title
        self.status = "running"
        self.log = []
        self.result = None
        self.error = ""
        self.started = time.time()
        self.finished = None

    def write(self, message):
        line = f"{time.strftime('%H:%M:%S')} {message}"
        with _lock:
            self.log.append(line)
            del self.log[:-400]
        print(f"[{self.kind}:{self.slug}] {message}", flush=True)

    def as_dict(self):
        with _lock:
            return {"id": self.id, "kind": self.kind, "slug": self.slug, "title": self.title,
                    "status": self.status, "log": self.log[-80:], "result": self.result, "error": self.error,
                    "elapsed": int((self.finished or time.time()) - self.started)}


def start(kind, slug, title, func):
    """Run ``func(job)`` in a thread. Only one job per (kind, slug) runs at a time."""
    with _lock:
        for job in _jobs.values():
            if job.kind == kind and job.slug == slug and job.status == "running":
                return job, False
        job = Job(kind, slug, title)
        _jobs[job.id] = job

    def run():
        try:
            job.result = func(job)
            job.status = "done"
        except Exception as exc:  # surfaced in the UI, never crashes the server
            job.error = str(exc)
            job.status = "error"
            job.write(f"失败：{exc}")
            traceback.print_exc()
        finally:
            job.finished = time.time()

    threading.Thread(target=run, daemon=True).start()
    return job, True


def get(job_id):
    return _jobs.get(job_id)


def recent(slug=None, limit=10):
    with _lock:
        items = [j for j in _jobs.values() if slug is None or j.slug == slug]
    items.sort(key=lambda j: -j.started)
    return [j.as_dict() for j in items[:limit]]
