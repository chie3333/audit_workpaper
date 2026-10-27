"""기획서 9번 확인 항목과 경계 사례 테스트."""
import copy
import json

import pytest

from app import content, engine, records, samples


def wp_data(wid):
    return records.load_workpaper(wid)


def calc(wp, data=None):
    return engine.compute(wp["content"], data or wp["data"])


def items(c, level=None):
    return [i["message"] for i in c["open_items"] if level is None or i["level"] == level]


# ---------------------------------------------------------------- 콘텐츠
def test_content_valid():
    rep = content.validate_all()
    assert all(r["ok"] for r in rep.values()), rep


def test_content_rejects_unmapped_reference(tmp_content):
    p = tmp_content / "templates" / "schedule_recon.json"
    t = json.loads(p.read_text(encoding="utf-8"))
    t["steps"][0]["guidance"][0]["refs"] = ["KSA2026:505.7"]  # 근거매핑에 없는 문단
    p.write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(content.ContentError) as e:
        content.resolve("cash.schedule_recon")
    assert any("근거매핑에서 확인하지 않은 위치" in m for m in e.value.errors)


def test_content_rejects_unknown_rule(tmp_content):
    p = tmp_content / "templates" / "schedule_recon.json"
    t = json.loads(p.read_text(encoding="utf-8"))
    t["steps"][2]["calcs"].append("magic_calc")
    t["checks"].append("auto_conclude")
    p.write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(content.ContentError) as e:
        content.resolve("cash.schedule_recon")
    assert any("magic_calc" in m for m in e.value.errors) and any("auto_conclude" in m for m in e.value.errors)


def test_guidance_defaults_to_ai_draft(resolved):
    for s in resolved["steps"]:
        for g in s["guidance"]:
            assert g["review"]["status"] == "AI 초안"
    assert resolved["assertions"]["default"] == ["C", "V"]


def test_content_version_pinned(tmp_content):
    cid = records.create_company("버전회사")
    eid = records.create_engagement(cid, "2025-12-31")
    w1 = records.create_workpaper(eid, "cash.schedule_recon")
    old = records.load_workpaper(w1)["content"]
    p = tmp_content / "templates" / "schedule_recon.json"
    t = json.loads(p.read_text(encoding="utf-8"))
    t["steps"][0]["guidance"][1]["text"] = "고친 안내 문구"
    p.write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
    # 내용을 바꾸고 버전을 그대로 두면 새 조서를 만들 수 없다
    with pytest.raises(records.Conflict):
        records.create_workpaper(eid, "cash.schedule_recon")
    t["version"] = "0.1.1"
    p.write_text(json.dumps(t, ensure_ascii=False), encoding="utf-8")
    w2 = records.create_workpaper(eid, "cash.schedule_recon")
    assert records.load_workpaper(w2)["content"]["steps"][0]["guidance"][1]["text"] == "고친 안내 문구"
    # 기존 조서는 만들 때의 콘텐츠를 그대로 쓴다
    assert records.load_workpaper(w1)["content"] == old


# ---------------------------------------------------------------- 빈칸과 0원
def test_blank_is_not_zero():
    st = {"id": "s", "stated_total": "0", "rows": [
        {"id": "a", "schedule_amount": "", "subledger_amount": "0"},
        {"id": "b", "schedule_amount": "0", "subledger_amount": "0"}]}
    c = engine.compute_set(st, "")
    assert c["rows"]["a"]["diff"] is None
    assert c["rows"]["b"]["diff"] == 0
    assert c["recalc_total"] is None  # 빈칸이 있으면 합계를 계산하지 않음
    assert c["subledger_total"] == 0
    assert c["stated_total"] == 0 and c["stated_vs_recalc"] is None
    assert c["gl_balance"] is None and c["subledger_vs_gl"] is None


def test_amount_parsing():
    assert engine.parse_amount("1,234") == (1234, None)
    assert engine.parse_amount("(500)") == (-500, None)
    assert engine.parse_amount("12.5")[1] == "원 단위 정수만 입력"
    assert engine.parse_amount("abc")[1] == "숫자가 아님"
    assert engine.parse_amount("  ") == (None, None)


# ---------------------------------------------------------------- 가상 사례 3종
def test_case_normal(seeded):
    wp = wp_data(seeded[0])
    c = calc(wp)
    assert c["status"]["blocking_count"] == 0, items(c, "block")
    s = c["sets"]["s_orig"]
    assert (s["recalc_total"], s["stated_vs_recalc"], s["subledger_vs_gl"]) == (20_500_000, 0, 0)


def test_case_difference(seeded):
    wp = wp_data(seeded[1])
    c = calc(wp)
    s = c["sets"]["s_orig"]
    assert s["recalc_total"] == 20_400_000 and s["stated_vs_recalc"] == 100_000
    assert s["rows"]["r1"]["diff"] == -100_000 and s["subledger_vs_gl"] == 0
    assert {d["key"] for d in c["diffs"]} == {"set:s_orig:stated_vs_recalc", "set:s_orig:row:r1"}
    assert all(d["has_finding"] for d in c["diffs"])
    assert c["status"]["findings_unresolved"] == 2
    assert c["status"]["review"] == "미검토"


def test_case_missing(seeded):
    wp = wp_data(seeded[2])
    c = calc(wp)
    msgs = items(c, "block")
    assert any("미입수 자료: 보조원장_K02" in m for m in msgs)
    assert any("[수정본 명세서] 보조부 금액 미입력 1건" in m for m in msgs)
    # 원본 대사 기록은 보존되고 수정본과 따로 계산된다
    assert c["sets"]["s_orig"]["recalc_total"] == 20_400_000
    assert c["sets"]["s_rev"]["recalc_total"] == 20_500_000
    assert c["sets"]["s_rev"]["subledger_total"] is None
    # 수정 전 세트의 빈칸은 남은 작업으로 다시 세지 않는다
    assert not any("[원본 명세서] 보조부 금액 미입력" in m for m in msgs)


def test_difference_needs_finding(resolved):
    d = samples.difference(resolved)
    d["findings"] = []
    c = engine.compute(resolved, d)
    assert sum("발견 사항 기록 없음" in m for m in items(c, "block")) == 2


def test_revised_schedule_requires_recheck(resolved):
    d = samples.normal(resolved)
    d["materials"].append({"id": "m_new", "role": "schedule", "name": "명세_v2", "kind": "수정본", "original_id": "m_sched",
                           "receipt": "입수", "confirmed": False})
    c = engine.compute(resolved, d)
    assert any("수정본 기준 재대사 기록 없음" in m for m in items(c, "block"))
    assert c["ui"]["unused_revised_schedules"] == ["m_new"]


# ---------------------------------------------------------------- 입력 수정 시 재계산
def test_recalc_on_edit(resolved):
    d = samples.difference(resolved)
    before = engine.compute(resolved, d)["sets"]["s_orig"]["rows"]["r1"]["diff"]
    d["recon"]["sets"][0]["rows"][0]["schedule_amount"] = "12,500,000"
    after = engine.compute(resolved, d)
    assert before == -100_000 and after["sets"]["s_orig"]["rows"]["r1"]["diff"] == 0
    assert after["sets"]["s_orig"]["stated_vs_recalc"] == 0
    # 차이가 사라져도 기존 발견 사항은 남고, 연결 상태가 바뀐 것을 보여준다
    assert after["ui"]["findings"]["f2"]["link_state"] == "zero_or_blank"


# ---------------------------------------------------------------- 상태 분리
def test_statuses_are_independent(resolved):
    d = samples.difference(resolved)
    d["fields"]["procedure_status"] = "수행 완료"
    c = engine.compute(resolved, d)
    assert c["status"]["procedure"] == "수행 완료"
    assert c["status"]["findings_unresolved"] == 2  # 수행 완료가 발견 사항을 해소하지 않음
    assert c["status"]["review"] == "미검토"  # 검토 상태도 바뀌지 않음
    assert any("수행 완료로 표시했으나" in m for m in items(c, "warn"))


def test_explanation_only_not_resolution(resolved):
    d = samples.difference(resolved)
    f = d["findings"][0]
    f["status"] = "처리 완료"
    c = engine.compute(resolved, d)
    assert any("처리 내용·근거 미기록" in m for m in items(c, "block"))
    f["resolution"], f["resolution_basis"] = "설명 들음", "담당자 설명"
    c = engine.compute(resolved, d)
    assert any("자료 재확인 없이 처리 완료" in m for m in items(c, "warn"))


def test_registered_vs_confirmed(resolved):
    d = samples.normal(resolved)
    d["materials"][0]["confirmed"] = False
    c = engine.compute(resolved, d)
    assert any("등록만 되어 있고 증거 확인 기록 없음" in m for m in items(c, "warn"))
    d["materials"][0].update({"confirmed": True, "confirmed_scope": ""})
    c = engine.compute(resolved, d)
    assert any("확인 범위" in m for m in items(c, "block"))


def test_review_complete_requires_record(resolved):
    d = samples.normal(resolved)
    d["fields"]["review_scope"] = ""
    c = engine.compute(resolved, d)
    assert any("검토 완료로 표시했으나 검토 범위 없음" in m for m in items(c, "block"))


def test_fs_link_statement_rules(resolved):
    d = samples.difference(resolved)
    c = engine.compute(resolved, d)
    assert c["visible"]["fs_link_statement"] is False  # 확인 중이면 명시 문장 칸이 없다
    d["fields"]["fs_link_status"] = "일치 확인"
    c = engine.compute(resolved, d)
    assert c["visible"]["fs_link_statement"] is True
    assert any("명시 문장" in m for m in items(c, "block"))


def test_assertion_change_needs_reason(resolved):
    d = samples.normal(resolved)
    d["assertions"]["applied"] = ["C", "V", "E"]
    c = engine.compute(resolved, d)
    assert any("변경 이유 없음" in m for m in items(c, "block"))
    d["assertions"]["change_reason"] = "이 업무에서는 ~ 때문에"
    assert not any("변경 이유 없음" in m for m in items(engine.compute(resolved, d), "block"))


def test_alternative_procedure_fields(resolved):
    d = samples.normal(resolved)
    d["fields"]["procedure_status"] = "대체절차 수행"
    c = engine.compute(resolved, d)
    blocks = items(c, "block")
    assert all(any(lab in m for m in blocks) for lab in ("수행한 대체절차", "대체절차가 목적을 달성한 방법", "이탈 이유"))
    d["fields"]["procedure_status"] = "해당 없음"
    assert any("해당 없음 사유" in m for m in items(engine.compute(resolved, d), "block"))


# ---------------------------------------------------------------- 고정 식별자
def test_row_reorder_keeps_links(resolved):
    d = samples.difference(resolved)
    d["recon"]["sets"][0]["rows"].reverse()
    d["recon"]["sets"][0]["rows"].insert(0, {"id": "r_new", "item_id": "K00", "schedule_amount": "0", "subledger_amount": "0"})
    c = engine.compute(resolved, d)
    assert c["sets"]["s_orig"]["rows"]["r1"]["diff"] == -100_000
    assert all(x["has_finding"] for x in c["diffs"])


# ---------------------------------------------------------------- 저장·리비전·잠금
def test_revisions_preserved(seeded):
    wid = seeded[1]
    wp = wp_data(wid)
    d = copy.deepcopy(wp["data"])
    d["recon"]["sets"][0]["rows"][0]["schedule_amount"] = "99"
    rn = records.save_workpaper(wid, d, base_rev=wp["rev"], note="수정")
    assert rn == wp["rev"] + 1
    assert records.load_workpaper(wid, wp["rev"])["data"] == wp["data"]
    assert records.load_workpaper(wid)["data"]["recon"]["sets"][0]["rows"][0]["schedule_amount"] == "99"


def test_stale_save_conflict(seeded):
    wid = seeded[0]
    wp = wp_data(wid)
    records.save_workpaper(wid, wp["data"], base_rev=wp["rev"])
    with pytest.raises(records.Conflict):
        records.save_workpaper(wid, wp["data"], base_rev=wp["rev"])


def test_lock_requires_reason(seeded):
    wid = seeded[0]
    records.set_lock(wid, True, "검토 끝남")
    wp = wp_data(wid)
    with pytest.raises(records.RecordError):
        records.save_workpaper(wid, wp["data"], base_rev=wp["rev"])
    rn = records.save_workpaper(wid, wp["data"], base_rev=wp["rev"], change_reason="오타 수정")
    revs = records.revisions(wid)
    assert revs["revisions"][0]["rev_no"] == rn and revs["revisions"][0]["change_reason"] == "오타 수정"
    assert revs["lock_events"][0]["reason"] == "검토 끝남"


# ---------------------------------------------------------------- 회사·기간 분리
def test_company_period_separation():
    a = records.create_company("가")
    b = records.create_company("나")
    ea1 = records.create_engagement(a, "2025-12-31")
    ea2 = records.create_engagement(a, "2024-12-31")
    eb = records.create_engagement(b, "2025-12-31")
    with pytest.raises(records.RecordError):
        records.create_engagement(a, "2025-12-31")
    w = {e: records.create_workpaper(e, "cash.schedule_recon") for e in (ea1, ea2, eb)}
    wp = wp_data(w[ea1])
    d = copy.deepcopy(wp["data"])
    d["fields"]["wp_no"] = "A-200-가-2025"
    records.save_workpaper(w[ea1], d, base_rev=1)
    assert wp_data(w[ea2])["data"]["fields"].get("wp_no") is None
    assert wp_data(w[eb])["data"]["fields"].get("wp_no") is None
    assert wp_data(w[ea2])["data"]["fields"]["as_of_date"] == "2024-12-31"
    tree = {c["name"]: c for c in records.tree()}
    assert len(tree["가"]["engagements"]) == 2 and len(tree["나"]["engagements"]) == 1
