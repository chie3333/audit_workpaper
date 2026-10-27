"""웹 서버. 실행: uvicorn app.main:app --reload"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import content, engine, export, records

STATIC = Path(__file__).resolve().parent / "static"
app = FastAPI(title="실증절차 조서 작성")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


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


@app.post("/api/workpapers")
def create_workpaper(body: dict = Body(...)):
    try:
        return {"id": records.create_workpaper(int(body["engagement_id"]), body["procedure_id"])}
    except Exception as e:
        _err(e)


def _bundle(wp: dict) -> dict:
    return wp | {"computed": engine.compute(wp["content"], wp["data"])}


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
        return engine.compute(wp["content"], body["data"])
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
