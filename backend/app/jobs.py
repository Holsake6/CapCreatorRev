"""The single background refresh job started from the review page."""

import threading
import time

from . import db
from .discovery import RefreshCancelled, run_refresh


class RefreshJob:
    def __init__(self, db_path=None):
        self.db_path = db_path
        self.lock = threading.Lock()
        self.cancel_event = None
        self.state = {"running": False, "message": "可以刷新", "logs": [], "finished": False,
                      "error": False, "cancel_requested": False, "started_at": 0}

    def snapshot(self):
        with self.lock:
            state = {**self.state, "logs": list(self.state["logs"])}
        if state["running"] and state["started_at"]:
            state["elapsed_seconds"] = int(time.time() - state["started_at"])
        return state

    def _log(self, stage, message):
        with self.lock:
            if not self.state["cancel_requested"] or stage in {"已停止", "失败", "完成"}:
                self.state["message"] = message
            self.state["logs"] = [*self.state["logs"], {
                "time": time.strftime("%H:%M:%S"), "stage": stage, "message": message}][-200:]

    def start(self):
        """Start a refresh; returns False if one is already running."""
        with self.lock:
            if self.state["running"]:
                return False
            self.cancel_event = threading.Event()
            self.state.update(running=True, message="正在启动扫描…", finished=False, error=False,
                              cancel_requested=False, started_at=time.time(),
                              logs=[{"time": time.strftime("%H:%M:%S"), "stage": "启动", "message": "正在启动扫描…"}])
        threading.Thread(target=self._run, args=(self.cancel_event,), daemon=True).start()
        return True

    def cancel(self):
        with self.lock:
            if not self.state["running"]:
                return False
        self._log("停止请求", "已请求停止，正在结束当前扫描批次…")
        with self.lock:
            self.state["cancel_requested"] = True
            self.cancel_event.set()
        return True

    def _run(self, cancel_event):
        outcome = {}
        try:
            with db.session(self.db_path) as conn:
                message, changed = run_refresh(conn, 1200, replace_pending=True, cancel_event=cancel_event,
                                               progress=self._log, mode="manual")
            self._log("完成", message)
            outcome = dict(message=message, finished=changed, error=False)
        except RefreshCancelled as exc:
            self._log("已停止", str(exc))
            outcome = dict(message=str(exc), finished=False, error=False)
        except Exception as exc:
            self._log("失败", f"刷新失败：{exc}")
            outcome = dict(message=f"刷新失败：{exc}", finished=False, error=True)
        finally:
            with self.lock:
                self.state.update(running=False, **outcome)
