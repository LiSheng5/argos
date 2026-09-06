"""Run / Event / Settings 落盘（SQLite，标准库自带，零新依赖）。

为什么用 SQLite 而不是跟着记忆卡用 JSON：Run 会一直攒（一次指令一条），
需要"按时间倒序翻页 + 按状态筛 + 按 id 查"，JSON 全量读写越跑越慢，
还要自己处理并发写（tick 线程和请求线程会同时写）。sqlite3 是标准库，
不引入任何新依赖。

线程模型：tick 在 to_thread 里跑，HTTP 在事件循环里跑，两边都会写库。
所以这里**单连接 + 一把锁**，check_same_thread=False。SQLite 本地写入很快，
一把锁不会成为瓶颈（真瓶颈是执行器的十几秒长动作，不在这里）。
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Dict, List, Optional

from argos.web.models import (Event, RobotProfile, CameraConfig, Run, Stage,
                              to_dict)

_DEFAULT_DB = Path(__file__).resolve().parent.parent / "store" / "argos.db"


class Store:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self.path = Path(db_path) if db_path else _DEFAULT_DB
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            cur = self._conn.cursor()
            cur.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id          TEXT PRIMARY KEY,
                    created_at  REAL NOT NULL,
                    updated_at  REAL NOT NULL,
                    status      TEXT NOT NULL,
                    source      TEXT NOT NULL,
                    command     TEXT,
                    reply       TEXT,
                    error       TEXT,
                    payload     TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_runs_created
                    ON runs(created_at DESC);

                CREATE TABLE IF NOT EXISTS events (
                    id       TEXT PRIMARY KEY,
                    ts       REAL NOT NULL,
                    type     TEXT NOT NULL,
                    category TEXT NOT NULL,
                    message  TEXT,
                    run_id   TEXT,
                    data     TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts DESC);
                CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id);

                CREATE TABLE IF NOT EXISTS settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                """
            )
            self._conn.commit()

    # ── Run ───────────────────────────────────────────

    def save_run(self, run: Run) -> Run:
        payload = json.dumps(to_dict(run), ensure_ascii=False)
        with self._lock:
            self._conn.execute(
                "INSERT INTO runs(id, created_at, updated_at, status, source,"
                " command, reply, error, payload) VALUES(?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET updated_at=excluded.updated_at,"
                " status=excluded.status, reply=excluded.reply,"
                " error=excluded.error, payload=excluded.payload",
                (run.id, run.createdAt, run.updatedAt, run.status, run.source,
                 run.command, run.reply, run.error, payload))
            self._conn.commit()
        return run

    def get_run(self, run_id: str) -> Optional[Run]:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload FROM runs WHERE id=?", (run_id,)).fetchone()
        return _run_from_json(row["payload"]) if row else None

    def list_runs(self, limit: int = 50, status: Optional[str] = None,
                  source: Optional[str] = None) -> List[Run]:
        sql = "SELECT payload FROM runs"
        args: List = []
        conds = []
        if status:
            conds.append("status=?")
            args.append(status)
        if source:
            conds.append("source=?")
            args.append(source)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(int(limit))
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [r for r in (_run_from_json(x["payload"]) for x in rows) if r]

    # ── Event ─────────────────────────────────────────

    def save_event(self, ev: Event) -> Event:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO events(id, ts, type, category,"
                " message, run_id, data) VALUES(?,?,?,?,?,?,?)",
                (ev.id, ev.ts, ev.type, ev.category, ev.message, ev.runId,
                 json.dumps(ev.data, ensure_ascii=False) if ev.data else None))
            self._conn.commit()
        return ev

    def list_events(self, limit: int = 100, run_id: Optional[str] = None,
                    category: Optional[str] = None) -> List[Event]:
        sql = "SELECT * FROM events"
        args: List = []
        conds = []
        if run_id:
            conds.append("run_id=?")
            args.append(run_id)
        if category:
            conds.append("category=?")
            args.append(category)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY ts DESC LIMIT ?"
        args.append(int(limit))
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [_event_from_row(r) for r in rows]

    # ── Settings（机器人档案 / 相机配置等）──────────────

    def get_setting(self, key: str, default=None):
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except ValueError:
            return default

    def set_setting(self, key: str, value) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO settings(key, value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value, ensure_ascii=False)))
            self._conn.commit()

    def get_profile(self) -> RobotProfile:
        data = self.get_setting("robot_profile") or {}
        return RobotProfile(id=data.get("id", "ARGOS-01"),
                            name=data.get("name", "ARGOS-01"),
                            imageUrl=data.get("imageUrl"),
                            updatedAt=data.get("updatedAt"))

    def set_profile(self, profile: RobotProfile) -> RobotProfile:
        self.set_setting("robot_profile", to_dict(profile))
        return profile

    def get_camera(self) -> CameraConfig:
        data = self.get_setting("camera") or {}
        return CameraConfig(mode=data.get("mode", "none"),
                            url=data.get("url"),
                            usbIndex=int(data.get("usbIndex", 0) or 0))

    def set_camera(self, cfg: CameraConfig) -> CameraConfig:
        self.set_setting("camera", to_dict(cfg))
        return cfg

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def _run_from_json(raw: str) -> Optional[Run]:
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    try:
        stages = [Stage(**s) for s in data.pop("stages", [])]
        run = Run(**data)
        run.stages = stages
        return run
    except TypeError:
        return None


def _event_from_row(row: sqlite3.Row) -> Event:
    raw = row["data"]
    data = None
    if raw:
        try:
            data = json.loads(raw)
        except ValueError:
            data = None
    return Event(id=row["id"], ts=row["ts"], type=row["type"],
                 category=row["category"], message=row["message"] or "",
                 runId=row["run_id"], data=data)


# 模块级默认库（gateway 装配时用，测试各自 new 一个临时库）
_default: Optional[Store] = None


def default_store() -> Store:
    global _default
    if _default is None:
        _default = Store()
    return _default


def set_default_store(store: Optional[Store]) -> None:
    global _default
    _default = store
