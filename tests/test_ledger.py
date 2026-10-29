"""정산표·재무제표·계정원장·분개장 계산과, 조서의 계정과목 참조."""
import copy
import io

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from app import engine, export, records, samples
from app.main import app


def _ledger():
    return copy.deepcopy(samples.ledger())


def _acct(L, code):
    return next(a for a in L["accounts"] if a["code"] == code)


# ---------------------------------------------------------------- 계산
def test_sample_ledger_ties_out():
    c = engine.compute_ledger(_ledger())
    assert c["errors"] == []
    for col in ("unadjusted", "adjusted"):
        assert c["tb_totals"][col]["diff"] == 0
    assert c["bs_totals"]["current"]["diff"] == 0 and c["bs_totals"]["prior"]["diff"] == 0
    assert c["income"]["net_income"] == 6_700_000
    for code, a in c["accounts"].items():
        assert (a["unadjusted_vs_journal"], a["adjustment_vs_journal"], a["adjusted_check"]) == (0, 0, 0), code
    assert all(g["diff"] == 0 for g in c["journal"].values())
    fs = {l["name"]: l for l in c["fs_lines"]}
    assert fs["현금및현금성자산"]["current"] == 20_500_000 and fs["현금및현금성자산"]["accounts"] == ["10301", "10302"]
    assert fs["이익잉여금"]["includes_net_income"] and fs["이익잉여금"]["current"] == 14_000_000 + 6_700_000
    assert c["accounts"]["10301"]["change"] == -2_500_000


def test_blank_amount_is_not_zero():
    L = _ledger()
    _acct(L, "10302")["adjusted"] = ""
    c = engine.compute_ledger(L)
    assert c["accounts"]["10302"]["change"] is None
    assert c["tb_totals"]["adjusted"]["debit"] is None
    assert next(l for l in c["fs_lines"] if l["name"] == "현금및현금성자산")["current"] is None
    assert c["bs_totals"]["current"]["diff"] is None


def test_mismatches_are_shown():
    L = _ledger()
    L["journal"].append({"id": "X-1", "je_no": "X", "line": 1, "date": "2025-12-01", "code": "10301",
                         "description": "한쪽만", "debit": 100, "credit": 0, "kind": "일반"})
    c = engine.compute_ledger(L)
    assert c["journal"]["X"]["diff"] == 100
    assert c["accounts"]["10301"]["unadjusted_vs_journal"] == -100
    L["journal"].append({"id": "Y-1", "je_no": "Y", "line": 1, "code": "99999", "debit": 1, "credit": 0})
    assert any("정산표에 없는 계정" in e[2] for e in engine.compute_ledger(L)["errors"])


def test_account_ledger_running_balance():
    L = _ledger()
    g = engine.account_ledger(L, "10301")
    assert g["calc"]["opening"] == 15_000_000
    assert [ln["balance"] for ln in g["lines"]] == [42_000_000, 23_500_000, 20_500_000, 12_500_000]
    assert g["closing_vs_adjusted"] == 0
    # 대변 잔액 계정은 대변 기준 양수로 쌓인다
    g = engine.account_ledger(L, "25100")
    assert g["calc"]["side"] == -1 and g["closing"] == 7_500_000
    # 수정분개는 일반 분개 뒤
    g = engine.account_ledger(L, "80100")
    assert [ln["kind"] for ln in g["lines"]] == ["일반", "수정분개"] and g["calc"]["opening"] == 0


# ---------------------------------------------------------------- 조서 참조
def _msgs(c, level):
    return [i["message"] for i in c["open_items"] if i["level"] == level]


def test_workpaper_link_checks(resolved):
    d = records.default_data(resolved, "2025-12-31")
    assert d["linked_accounts"] == []
    c = engine.compute(resolved, d, None)
    assert any("정산표가 없음" in m for m in _msgs(c, "info"))
    c = engine.compute(resolved, d, _ledger())
    assert any("계정과목을 선택하지 않음" in m for m in _msgs(c, "warn"))
    d["linked_accounts"] = ["10301", "10302"]
    d["recon"]["gl_balance"] = "20500000"
    c = engine.compute(resolved, d, _ledger())
    assert c["linked"]["adjusted"] == 20_500_000 and c["linked"]["change"] == 5_500_000
    assert not any("정산표" in m for m in _msgs(c, "warn"))
    d["linked_accounts"] = ["10301"]
    c = engine.compute(resolved, d, _ledger())
    assert any("정산표 수정후 합계 12,500,000원과 입력한 총계정원장 잔액 20,500,000원이 다름" in m for m in _msgs(c, "warn"))
    # 참조값은 입력값을 바꾸지 않는다
    assert d["recon"]["gl_balance"] == "20500000"


# ---------------------------------------------------------------- 가상 사례·API·엑셀
def test_sample_consistency():
    L = samples.ledger()
    assert _acct(L, "10301")["adjusted"] == 12_500_000 and _acct(L, "10302")["adjusted"] == 8_000_000
    j006 = next(ln for ln in L["journal"] if ln["je_no"] == "J006" and ln["code"] == "10302")
    from app import content
    k02 = next(r for r in samples.classification(content.resolve(samples.CLS_BINDING))["classify"]["rows"] if r["item_id"] == "K02")
    assert j006["date"] == k02["acquired_date"]


def test_api_and_seed(seeded):
    cl = TestClient(app)
    tree = cl.get("/api/tree").json()
    has = {c["name"]: c["engagements"][0]["has_ledger"] for c in tree}
    assert has == {"가상 차이(주)": True, "가상 정상(주)": False, "가상 자료부족(주)": False}
    wp = records.load_workpaper(seeded[1])
    eid = wp["engagement_id"]
    r = cl.get(f"/api/engagements/{eid}/ledger").json()
    assert r["computed"]["tb_totals"]["adjusted"]["diff"] == 0
    linked = {w["wp_no"]: w["linked_accounts"] for w in r["engagement"]["workpapers"]}
    assert linked == {"A-200": ["10301", "10302"], "A-210": ["10301", "10302"]}
    assert cl.get(f"/api/engagements/{eid}/ledger/accounts/10302").json()["lines"][0]["je_no"] == "J006"
    assert cl.get(f"/api/engagements/{eid}/ledger/accounts/00000").status_code == 404
    other = records.load_workpaper(seeded[0])["engagement_id"]
    assert cl.get(f"/api/engagements/{other}/ledger").json()["ledger"] is None
    assert cl.get(f"/api/engagements/{other}/ledger/accounts/10301").status_code == 404
    got = cl.get(f"/api/workpapers/{seeded[1]}").json()
    assert got["computed"]["linked"]["adjusted"] == 20_500_000


def test_export_shows_linked_accounts(seeded):
    wp = records.load_workpaper(seeded[1])
    data, _ = export.build(wp)
    t = "\n".join(str(c.value) for row in load_workbook(io.BytesIO(data))["조서"].iter_rows() for c in row if c.value is not None)
    assert "10302 정기예금 (현금및현금성자산)" in t and "참조값" in t
    data, _ = export.build(records.load_workpaper(seeded[0]))
    t = "\n".join(str(c.value) for row in load_workbook(io.BytesIO(data))["조서"].iter_rows() for c in row if c.value is not None)
    assert "이 감사건에 정산표 없음" in t


def test_change_rate():
    assert engine.change_rate(5_500_000, 15_000_000) == 36.7
    assert engine.change_rate(-2_500_000, 15_000_000) == -16.7
    assert engine.change_rate(300_000, 0) is None  # 전기 0원: 증감률 없음(화면은 '신규')
    assert engine.change_rate(None, 100) is None and engine.change_rate(100, None) is None
    assert engine.change_rate(100, -200) == 50.0  # 전기가 음수여도 증가는 +
    c = engine.compute_ledger(_ledger())
    assert c["accounts"]["10301"]["change_rate"] == -16.7 and c["accounts"]["10302"]["change_rate"] is None
    cash = next(l for l in c["fs_lines"] if l["name"] == "현금및현금성자산")
    assert cash["change_rate"] == 36.7 and cash["tb_sums"]["change"] == 5_500_000
    assert c["bs_totals"]["change"]["자산"] == 8_500_000 and c["bs_totals"]["change_rate"]["자산"] == 28.3
    assert c["income"]["net_income_change"] == 1_700_000 and c["income"]["net_income_change_rate"] == 34.0
    link = engine.linked_accounts(_ledger(), ["10301", "10302"])
    assert link["change_rate"] == 36.7 and [r["change_rate"] for r in link["rows"]] == [-16.7, None]
    assert "증감 ▼ 2,500,000 (▼ 16.7%)" == export._chg(-2_500_000, -16.7, 15_000_000)
    assert "증감 ▲ 8,000,000 (신규)" == export._chg(8_000_000, None, 0)
