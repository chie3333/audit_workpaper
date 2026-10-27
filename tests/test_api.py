"""화면이 쓰는 API 흐름: 만들기 → 미리 계산 → 저장 → 다시 열기 → 엑셀."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_full_flow():
    cid = client.post("/api/companies", json={"name": "API회사"}).json()["id"]
    eid = client.post("/api/engagements", json={"company_id": cid, "period_end": "2025-12-31"}).json()["id"]
    wid = client.post("/api/workpapers", json={"engagement_id": eid, "procedure_id": "cash.schedule_recon"}).json()["id"]
    wp = client.get(f"/api/workpapers/{wid}").json()
    assert wp["rev"] == 1 and wp["data"]["fields"]["as_of_date"] == "2025-12-31"

    d = wp["data"]
    d["recon"]["sets"][0]["rows"] = [{"id": "r1", "item_id": "K01", "schedule_amount": "1,000", "subledger_amount": "900"}]
    d["recon"]["sets"][0]["stated_total"] = "1000"
    d["recon"]["gl_balance"] = "900"
    c = client.post(f"/api/workpapers/{wid}/preview", json={"data": d}).json()
    assert c["sets"][d["recon"]["sets"][0]["id"]]["rows"]["r1"]["diff"] == 100
    assert client.get(f"/api/workpapers/{wid}").json()["rev"] == 1  # preview는 저장하지 않음

    saved = client.post(f"/api/workpapers/{wid}/save", json={"data": d, "base_rev": 1, "note": "첫 입력"}).json()
    assert saved["rev"] == 2
    again = client.get(f"/api/workpapers/{wid}").json()
    assert again["data"]["recon"]["sets"][0]["rows"][0]["schedule_amount"] == "1,000"

    r = client.post(f"/api/workpapers/{wid}/save", json={"data": d, "base_rev": 1})
    assert r.status_code == 409

    x = client.get(f"/api/workpapers/{wid}/export.xlsx")
    assert x.status_code == 200 and x.content[:2] == b"PK"
    assert "attachment" in x.headers["content-disposition"]
    old = client.get(f"/api/workpapers/{wid}/export.xlsx?rev=1")
    assert old.status_code == 200


def test_bad_input_messages():
    assert client.post("/api/companies", json={"name": " "}).status_code == 400
    cid = client.post("/api/companies", json={"name": "중복"}).json()["id"]
    assert client.post("/api/companies", json={"name": "중복"}).status_code == 400
    assert client.post("/api/engagements", json={"company_id": cid, "period_end": "2025/12/31"}).status_code == 400
    assert client.get("/api/workpapers/9999").status_code == 400
