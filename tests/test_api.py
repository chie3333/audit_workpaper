"""화면이 쓰는 API 흐름: 만들기 → 미리 계산 → 저장 → 다시 열기 → 엑셀."""
from fastapi.testclient import TestClient

from app import records
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


def test_board_is_view_only_and_follows_engine(seeded):
    """조서 보드: 카드 상태는 engine 결과 그대로, 보드를 읽어도 리비전이 생기지 않는다."""
    from app import engine
    cl = TestClient(app)
    wp = records.load_workpaper(seeded[1])
    before = wp["rev"]
    b = cl.get(f"/api/engagements/{wp['engagement_id']}/board").json()
    cards = {c["wp_no"]: c for c in b["cards"]}
    assert set(cards) == {"A-200", "A-210"}
    c = engine.compute(wp["content"], wp["data"], wp["ledger"])["status"]
    assert (cards["A-200"]["procedure"], cards["A-200"]["review"], cards["A-200"]["blocking"]) == (c["procedure"], c["review"], c["blocking_count"])
    assert cards["A-200"]["accounts"] == ["10301 보통예금", "10302 정기예금"]
    assert sorted(f["status"] for f in b["findings"]) == ["미해결", "후속 확인 중", "후속 확인 중"]
    assert b["columns"]["findings"] == ["미해결", "후속 확인 중", "처리 완료"]
    assert records.load_workpaper(seeded[1])["rev"] == before
    empty = records.load_workpaper(seeded[0])["engagement_id"]
    assert cl.get(f"/api/engagements/{empty}/board").json()["findings"] == []
