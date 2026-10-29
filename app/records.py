"""조서 기록 저장 (SQLite).

- 회사 → 감사건(보고기간) → 조서 → 리비전
- 조서 내용은 저장할 때마다 새 리비전으로 쌓인다(덮어쓰지 않음).
- 조서는 만들 때의 콘텐츠 스냅샷을 가리킨다.
- 편집 잠금은 업무용 기능이다. 최종 감사파일 취합·법정 보존 기능이 아니다.
- 감사건마다 정산표·분개장(원장 자료)을 하나 둔다. 조서는 그 계정과목을 참조만 한다.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from . import content as content_mod

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "audit.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, role TEXT NOT NULL DEFAULT '작성자'
);
CREATE TABLE IF NOT EXISTS companies (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, is_sample INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS engagements (
  id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL REFERENCES companies(id),
  period_end TEXT NOT NULL, currency TEXT NOT NULL DEFAULT 'KRW', unit TEXT NOT NULL DEFAULT '원',
  created_at TEXT NOT NULL, UNIQUE(company_id, period_end)
);
CREATE TABLE IF NOT EXISTS content_snapshots (
  id INTEGER PRIMARY KEY, content_key TEXT NOT NULL UNIQUE, binding_id TEXT NOT NULL, version TEXT NOT NULL,
  hash TEXT NOT NULL, json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workpapers (
  id INTEGER PRIMARY KEY, engagement_id INTEGER NOT NULL REFERENCES engagements(id),
  snapshot_id INTEGER NOT NULL REFERENCES content_snapshots(id), title TEXT NOT NULL,
  created_at TEXT NOT NULL, locked INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS revisions (
  id INTEGER PRIMARY KEY, workpaper_id INTEGER NOT NULL REFERENCES workpapers(id), rev_no INTEGER NOT NULL,
  saved_at TEXT NOT NULL, saved_by TEXT NOT NULL, note TEXT, change_reason TEXT, data_json TEXT NOT NULL,
  UNIQUE(workpaper_id, rev_no)
);
CREATE TABLE IF NOT EXISTS ledgers (
  engagement_id INTEGER PRIMARY KEY REFERENCES engagements(id), source TEXT NOT NULL,
  data_json TEXT NOT NULL, loaded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS lock_events (
  id INTEGER PRIMARY KEY, workpaper_id INTEGER NOT NULL REFERENCES workpapers(id), locked INTEGER NOT NULL,
  reason TEXT, by TEXT NOT NULL, at TEXT NOT NULL
);
"""

DEFAULT_USER = "작성자"


class RecordError(Exception):
    pass


class Conflict(RecordError):
    pass


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:8]}"


def db_path() -> Path:
    return Path(os.environ.get("AUDIT_WP_DB", DEFAULT_DB))


@contextmanager
def connect():
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        con.executescript(SCHEMA)
        con.execute("INSERT OR IGNORE INTO users(name, role) VALUES (?, ?)", (DEFAULT_USER, "작성자"))
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


# ---------------------------------------------------------------- 회사·감사건
def create_company(name: str, is_sample: bool = False) -> int:
    name = name.strip()
    if not name:
        raise RecordError("회사명이 비어 있음")
    with connect() as con:
        try:
            cur = con.execute("INSERT INTO companies(name, is_sample, created_at) VALUES (?,?,?)", (name, int(is_sample), now()))
        except sqlite3.IntegrityError:
            raise RecordError(f"이미 있는 회사명: {name}")
        return cur.lastrowid


def create_engagement(company_id: int, period_end: str, currency: str = "KRW", unit: str = "원") -> int:
    try:
        datetime.strptime(period_end, "%Y-%m-%d")
    except ValueError:
        raise RecordError("보고기간 종료일 형식은 YYYY-MM-DD")
    with connect() as con:
        if not con.execute("SELECT 1 FROM companies WHERE id=?", (company_id,)).fetchone():
            raise RecordError("회사 없음")
        try:
            cur = con.execute("INSERT INTO engagements(company_id, period_end, currency, unit, created_at) VALUES (?,?,?,?,?)",
                              (company_id, period_end, currency, unit, now()))
        except sqlite3.IntegrityError:
            raise RecordError("같은 회사·보고기간의 감사건이 이미 있음")
        return cur.lastrowid


# ---------------------------------------------------------------- 원장 자료 (정산표·분개장)
def save_ledger(engagement_id: int, ledger: dict, source: str):
    """감사건의 정산표·분개장을 저장한다. 이미 있으면 바꾼다(1단계는 가상 데이터만)."""
    with connect() as con:
        if not con.execute("SELECT 1 FROM engagements WHERE id=?", (engagement_id,)).fetchone():
            raise RecordError("감사건 없음")
        con.execute("INSERT OR REPLACE INTO ledgers(engagement_id, source, data_json, loaded_at) VALUES (?,?,?,?)",
                    (engagement_id, source, json.dumps(ledger, ensure_ascii=False), now()))


def update_ledger(engagement_id: int, fn, source: str = "업로드") -> dict:
    """감사건의 원장 자료를 읽어 fn(ledger)로 고친 뒤 저장한다. 없으면 빈 자료에서 시작한다."""
    cur = load_ledger(engagement_id) or {"fs": [], "accounts": [], "adjustments": [], "journal": [], "sources": {}}
    cur = {k: v for k, v in cur.items() if not k.startswith("_")}
    fn(cur)
    save_ledger(engagement_id, cur, source)
    return cur


def load_ledger(engagement_id: int) -> dict | None:
    with connect() as con:
        row = con.execute("SELECT * FROM ledgers WHERE engagement_id=?", (engagement_id,)).fetchone()
        if not row:
            return None
        return json.loads(row["data_json"]) | {"_source": row["source"], "_loaded_at": row["loaded_at"]}


def engagement(engagement_id: int) -> dict:
    with connect() as con:
        e = con.execute("""SELECT e.*, c.name AS company, c.is_sample FROM engagements e JOIN companies c ON c.id=e.company_id
                           WHERE e.id=?""", (engagement_id,)).fetchone()
        if not e:
            raise RecordError("감사건 없음")
        wps = []
        for w in con.execute("SELECT w.id, w.title, r.data_json FROM workpapers w JOIN revisions r ON r.workpaper_id=w.id "
                             "WHERE w.engagement_id=? AND r.rev_no=(SELECT MAX(rev_no) FROM revisions WHERE workpaper_id=w.id) ORDER BY w.id",
                             (engagement_id,)):
            d = json.loads(w["data_json"])
            wps.append({"id": w["id"], "title": w["title"], "wp_no": d.get("fields", {}).get("wp_no", ""),
                        "linked_accounts": d.get("linked_accounts", [])})
        return {"id": e["id"], "company": e["company"], "company_id": e["company_id"], "is_sample": bool(e["is_sample"]),
                "period_end": e["period_end"],
                "currency": e["currency"], "unit": e["unit"], "workpapers": wps}


# ---------------------------------------------------------------- 콘텐츠 스냅샷
def snapshot_content(con, resolved: dict) -> int:
    row = con.execute("SELECT id, hash FROM content_snapshots WHERE content_key=?", (resolved["content_key"],)).fetchone()
    if row:
        if row["hash"] != resolved["hash"]:
            raise Conflict(f"콘텐츠 '{resolved['content_key']}'의 내용이 바뀌었는데 버전이 그대로임. 콘텐츠 버전을 올려야 함")
        return row["id"]
    cur = con.execute("INSERT INTO content_snapshots(content_key, binding_id, version, hash, json, created_at) VALUES (?,?,?,?,?,?)",
                      (resolved["content_key"], resolved["id"], resolved["version"], resolved["hash"],
                       json.dumps(resolved, ensure_ascii=False), now()))
    return cur.lastrowid


# ---------------------------------------------------------------- 조서
def default_data(resolved: dict, period_end: str) -> dict:
    """템플릿의 구성요소에 맞춰 빈 조서 기록을 만든다."""
    comps = {c["type"] for s in resolved["steps"] for c in s["components"]}
    data = {
        "fields": {"as_of_date": period_end, "procedure_status": "미착수", "review_status": "미검토"},
        "assertions": {"applied": list(resolved["assertions"]["default"]), "change_reason": ""},
        "materials": [],
    }
    if "recon" in comps:
        data["fields"]["list_check"] = "미수행"
        data["recon"] = {"sets": [{"id": new_id("s"), "label": "원본 명세서", "schedule_material_id": "", "stated_total": "",
                                   "stated_total_loc": "", "rows": []}],
                         "gl_balance": "", "gl_loc": "", "gl_material_id": ""}
    if "scan" in comps:
        data["scan"] = {"status": "미결정", "note": "", "na_reason": ""}
    if "classify" in comps:
        data["classify"] = {"schedule_material_id": "", "rows": []}
    if "accounts" in comps:
        data["linked_accounts"] = []
    data["findings"] = []
    data["review_comments"] = []
    return data


def create_workpaper(engagement_id: int, binding_id: str, by: str = DEFAULT_USER, linked_accounts: list[str] | None = None) -> int:
    resolved = content_mod.resolve(binding_id)
    with connect() as con:
        eng = con.execute("SELECT * FROM engagements WHERE id=?", (engagement_id,)).fetchone()
        if not eng:
            raise RecordError("감사건 없음")
        sid = snapshot_content(con, resolved)
        cur = con.execute("INSERT INTO workpapers(engagement_id, snapshot_id, title, created_at) VALUES (?,?,?,?)",
                          (engagement_id, sid, resolved["title"], now()))
        wid = cur.lastrowid
        data = default_data(resolved, eng["period_end"])
        if linked_accounts and "linked_accounts" in data:
            data["linked_accounts"] = list(linked_accounts)
        con.execute("INSERT INTO revisions(workpaper_id, rev_no, saved_at, saved_by, note, data_json) VALUES (?,?,?,?,?,?)",
                    (wid, 1, now(), by, "조서 생성", json.dumps(data, ensure_ascii=False)))
        return wid


def load_workpaper(wid: int, rev_no: int | None = None) -> dict:
    with connect() as con:
        wp = con.execute("""SELECT w.*, e.period_end, e.currency, e.unit, e.company_id, c.name AS company, c.is_sample,
                                   s.json AS content_json, s.content_key
                            FROM workpapers w JOIN engagements e ON e.id=w.engagement_id
                            JOIN companies c ON c.id=e.company_id JOIN content_snapshots s ON s.id=w.snapshot_id
                            WHERE w.id=?""", (wid,)).fetchone()
        if not wp:
            raise RecordError("조서 없음")
        latest = con.execute("SELECT MAX(rev_no) FROM revisions WHERE workpaper_id=?", (wid,)).fetchone()[0]
        rn = rev_no or latest
        rev = con.execute("SELECT * FROM revisions WHERE workpaper_id=? AND rev_no=?", (wid, rn)).fetchone()
        if not rev:
            raise RecordError("리비전 없음")
        out = {
            "id": wp["id"], "title": wp["title"], "company": wp["company"], "company_id": wp["company_id"],
            "is_sample": bool(wp["is_sample"]), "engagement_id": wp["engagement_id"], "period_end": wp["period_end"],
            "currency": wp["currency"], "unit": wp["unit"], "locked": bool(wp["locked"]),
            "content": json.loads(wp["content_json"]), "rev": rn, "latest_rev": latest,
            "saved_at": rev["saved_at"], "saved_by": rev["saved_by"], "data": json.loads(rev["data_json"]),
        }
    out["ledger"] = load_ledger(out["engagement_id"])
    return out


def save_workpaper(wid: int, data: dict, base_rev: int, by: str = DEFAULT_USER, note: str = "", change_reason: str = "") -> int:
    with connect() as con:
        wp = con.execute("SELECT locked FROM workpapers WHERE id=?", (wid,)).fetchone()
        if not wp:
            raise RecordError("조서 없음")
        latest = con.execute("SELECT MAX(rev_no) FROM revisions WHERE workpaper_id=?", (wid,)).fetchone()[0]
        if base_rev != latest:
            raise Conflict(f"다른 곳에서 먼저 저장됨 (현재 리비전 {latest}, 편집 기준 {base_rev}). 다시 불러온 뒤 저장해야 함")
        if wp["locked"] and not change_reason.strip():
            raise RecordError("잠긴 조서를 수정하려면 수정 이유가 필요함")
        rn = latest + 1
        con.execute("INSERT INTO revisions(workpaper_id, rev_no, saved_at, saved_by, note, change_reason, data_json) VALUES (?,?,?,?,?,?,?)",
                    (wid, rn, now(), by, note, change_reason or None, json.dumps(data, ensure_ascii=False)))
        return rn


def set_lock(wid: int, locked: bool, reason: str, by: str = DEFAULT_USER):
    if not reason.strip():
        raise RecordError("잠금·해제 사유가 필요함")
    with connect() as con:
        con.execute("UPDATE workpapers SET locked=? WHERE id=?", (int(locked), wid))
        con.execute("INSERT INTO lock_events(workpaper_id, locked, reason, by, at) VALUES (?,?,?,?,?)", (wid, int(locked), reason, by, now()))


def revisions(wid: int) -> dict:
    with connect() as con:
        revs = [dict(r) for r in con.execute(
            "SELECT rev_no, saved_at, saved_by, note, change_reason FROM revisions WHERE workpaper_id=? ORDER BY rev_no DESC", (wid,))]
        locks = [dict(r) for r in con.execute(
            "SELECT locked, reason, by, at FROM lock_events WHERE workpaper_id=? ORDER BY id DESC", (wid,))]
        return {"revisions": revs, "lock_events": locks}


def company(company_id: int) -> dict:
    for c in tree():
        if c["id"] == company_id:
            return c
    raise RecordError("회사 없음")


def tree() -> list[dict]:
    with connect() as con:
        out = []
        for c in con.execute("SELECT * FROM companies ORDER BY is_sample, name"):
            engs = []
            for e in con.execute("SELECT * FROM engagements WHERE company_id=? ORDER BY period_end DESC", (c["id"],)):
                wps = [dict(w) for w in con.execute(
                    """SELECT w.id, w.title, w.locked, s.content_key,
                              (SELECT MAX(rev_no) FROM revisions r WHERE r.workpaper_id=w.id) AS rev,
                              (SELECT saved_at FROM revisions r WHERE r.workpaper_id=w.id ORDER BY rev_no DESC LIMIT 1) AS saved_at
                       FROM workpapers w JOIN content_snapshots s ON s.id=w.snapshot_id WHERE w.engagement_id=? ORDER BY w.id""",
                    (e["id"],))]
                led = con.execute("SELECT data_json FROM ledgers WHERE engagement_id=?", (e["id"],)).fetchone()
                led = json.loads(led["data_json"]) if led else {}
                has_ledger = bool(led.get("fs") and led.get("accounts"))
                engs.append({"id": e["id"], "period_end": e["period_end"], "currency": e["currency"], "unit": e["unit"],
                             "has_ledger": has_ledger, "workpapers": wps})
            out.append({"id": c["id"], "name": c["name"], "is_sample": bool(c["is_sample"]), "engagements": engs})
        return out
