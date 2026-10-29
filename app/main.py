"""웹 서버. 실행: uvicorn app.main:app --reload"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import content, engine, export, imports, records

STATIC = Path(__file__).resolve().parent / "static"
app = FastAPI(title="실증절차 조서 작성")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def no_cache_static(request, call_next):
    """화면 파일을 고친 뒤 브라우저가 옛 파일을 쓰지 않도록 매번 다시 확인하게 한다."""
    res = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        res.headers["Cache-Control"] = "no-cache"
    return res


def _err(e: Exception):
    if isinstance(e, records.Conflict):
        raise HTTPException(409, str(e))
    if isinstance(e, content.ContentError):
        raise HTTPException(422, {"message": "콘텐츠 검증 실패", "errors": e.errors})
    if isinstance(e, records.RecordError):
        raise HTTPException(400, str(e))
    raise e


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/procedures")
def procedures():
    return content.list_bindings()


@app.get("/api/content/check")
def content_check():
    return content.validate_all()


@app.get("/api/tree")
def tree():
    return records.tree()


@app.get("/api/companies/{cid}")
def company(cid: int):
    try:
        return records.company(cid)
    except Exception as e:
        _err(e)


@app.post("/api/companies")
def create_company(body: dict = Body(...)):
    try:
        return {"id": records.create_company(body.get("name", ""), bool(body.get("is_sample")))}
    except Exception as e:
        _err(e)


@app.post("/api/engagements")
def create_engagement(body: dict = Body(...)):
    try:
        return {"id": records.create_engagement(int(body["company_id"]), body.get("period_end", ""),
                                                body.get("currency") or "KRW", body.get("unit") or "원")}
    except Exception as e:
        _err(e)


@app.get("/api/engagements/{eid}/ledger")
def ledger(eid: int):
    """재무제표 → 정산표 → 계정원장 → 분개장 탐색용. 계산은 engine에서."""
    try:
        eng = records.engagement(eid)
        led = records.load_ledger(eid)
    except Exception as e:
        _err(e)
    led = led or {"fs": [], "accounts": [], "adjustments": [], "journal": [], "sources": {}}
    groups = content.load_account_groups()
    return {"engagement": eng, "ledger": led, "computed": engine.compute_ledger(led, groups),
            "procedures": content.list_bindings(), "account_groups": groups}


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@app.get("/api/templates/{kind}.xlsx")
def template(kind: str):
    """재무제표·시산표 양식 (빈 양식)."""
    if kind not in ("fs", "tb"):
        raise HTTPException(404, "양식 없음")
    data = imports.write_fs() if kind == "fs" else imports.write_tb()
    name = "재무제표_양식.xlsx" if kind == "fs" else "시산표_양식.xlsx"
    return Response(data, media_type=XLSX, headers={"Content-Disposition": f"attachment; filename=\"{kind}.xlsx\"; filename*=UTF-8''{quote(name)}"})


@app.post("/api/engagements/{eid}/upload/{kind}")
async def upload(eid: int, kind: str, request: Request):
    """양식 엑셀 업로드. 본문은 파일 그대로(xlsx 바이트). 오류가 있으면 저장하지 않는다."""
    if kind not in ("fs", "tb"):
        raise HTTPException(404, "알 수 없는 자료")
    body = await request.body()
    filename = request.headers.get("x-filename", "")
    try:
        records.engagement(eid)
        parsed = imports.parse_fs(body) if kind == "fs" else imports.parse_tb(body)
    except imports.ImportError_ as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        _err(e)
    if parsed["errors"]:
        raise HTTPException(422, {"message": "양식 오류 — 저장하지 않음", "errors": parsed["errors"]})

    def apply(led):
        if kind == "fs":
            led["fs"] = parsed["rows"]
        else:
            led["accounts"] = parsed["accounts"]
        led.setdefault("sources", {})[kind] = {"filename": filename, "uploaded_at": records.now(),
                                               "rows": len(parsed.get("rows") or parsed.get("accounts"))}
    records.update_ledger(eid, apply)
    return ledger(eid)


@app.post("/api/engagements/{eid}/mapping")
def mapping(eid: int, body: dict = Body(...)):
    """계정과목 → 표시 항목 연결을 고친다. body: {"계정코드": "표시 항목"}"""
    def apply(led):
        for a in led.get("accounts", []):
            if a["code"] in body:
                a["fs_line"] = body[a["code"]] or ""
    records.update_ledger(eid, apply)
    return ledger(eid)


@app.post("/api/engagements/{eid}/adjustments")
def adjustments(eid: int, body: dict = Body(...)):
    """감사인 수정분개 전체를 저장한다. 차대 불일치 등은 계산 결과의 확인할 것에 표시된다."""
    items = body.get("adjustments", [])
    for a in items:
        if not a.get("id") or not isinstance(a.get("lines"), list):
            raise HTTPException(400, "수정분개 형식 오류")
    records.update_ledger(eid, lambda led: led.__setitem__("adjustments", items))
    return ledger(eid)


@app.post("/api/engagements/{eid}/groups")
def fs_groups(eid: int, body: dict = Body(...)):
    """표시 항목 → 공통 계정 분류를 직접 정한다. body: {"표시 항목": "분류 id" | "" (분류 없음) | null (자동으로 되돌림)}"""
    known = {g["id"] for g in content.load_account_groups()}
    bad = [v for v in body.values() if v and v not in known]
    if bad:
        raise HTTPException(400, f"공통 계정 분류에 없는 id: {bad}")

    def apply(led):
        for r in led.get("fs", []):
            if r["name"] in body:
                if body[r["name"]] is None:
                    r.pop("group", None)
                else:
                    r["group"] = body[r["name"]]
    records.update_ledger(eid, apply)
    return ledger(eid)


@app.post("/api/engagements/{eid}/settings")
def ledger_settings(eid: int, body: dict = Body(...)):
    records.update_ledger(eid, lambda led: led.__setitem__("net_income_line", body.get("net_income_line") or None))
    return ledger(eid)


@app.get("/api/engagements/{eid}/ledger/accounts/{code}")
def account_ledger(eid: int, code: str):
    led = records.load_ledger(eid)
    if not led or not led.get("accounts"):
        raise HTTPException(404, "이 감사건에 시산표가 없음")
    try:
        return engine.account_ledger(led, code)
    except KeyError:
        raise HTTPException(404, f"정산표에 없는 계정과목: {code}")


@app.post("/api/workpapers")
def create_workpaper(body: dict = Body(...)):
    try:
        return {"id": records.create_workpaper(int(body["engagement_id"]), body["procedure_id"],
                                               linked_accounts=body.get("linked_accounts"))}
    except Exception as e:
        _err(e)


def _bundle(wp: dict) -> dict:
    groups = {}
    if wp["ledger"] and wp["ledger"].get("accounts"):
        groups = {c: a["group"] for c, a in engine.compute_ledger(wp["ledger"], content.load_account_groups())["accounts"].items()}
    return wp | {"computed": engine.compute(wp["content"], wp["data"], wp["ledger"]), "account_group_of": groups}


@app.get("/api/workpapers/{wid}")
def get_workpaper(wid: int, rev: int | None = None):
    try:
        return _bundle(records.load_workpaper(wid, rev))
    except Exception as e:
        _err(e)


@app.post("/api/workpapers/{wid}/preview")
def preview(wid: int, body: dict = Body(...)):
    try:
        wp = records.load_workpaper(wid)
        return engine.compute(wp["content"], body["data"], wp["ledger"])
    except Exception as e:
        _err(e)


@app.post("/api/workpapers/{wid}/save")
def save(wid: int, body: dict = Body(...)):
    try:
        rn = records.save_workpaper(wid, body["data"], int(body["base_rev"]), note=body.get("note", ""),
                                    change_reason=body.get("change_reason", ""))
        return _bundle(records.load_workpaper(wid, rn))
    except Exception as e:
        _err(e)


@app.get("/api/workpapers/{wid}/revisions")
def revisions(wid: int):
    return records.revisions(wid)


@app.post("/api/workpapers/{wid}/lock")
def lock(wid: int, body: dict = Body(...)):
    try:
        records.set_lock(wid, bool(body.get("locked")), body.get("reason", ""))
        return {"ok": True}
    except Exception as e:
        _err(e)


@app.get("/api/workpapers/{wid}/export.xlsx")
def export_xlsx(wid: int, rev: int | None = None):
    try:
        wp = records.load_workpaper(wid, rev)
    except Exception as e:
        _err(e)
    data, _ = export.build(wp)
    wp_no = wp["data"]["fields"].get("wp_no") or f"WP{wid}"
    name = f"{wp['company']}_{wp_no}_{wp['period_end']}_r{wp['rev']}.xlsx"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename=\"workpaper_{wid}_r{wp['rev']}.xlsx\"; filename*=UTF-8''{quote(name)}"})
