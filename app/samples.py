"""가상 사례 3종 (정상 / 차이 / 자료 부족).

전부 가상 데이터다. 회사·금융기관·계좌·금액·사람은 실재하지 않으며 실제 감사 수행 기록이 아니다.
화면과 엑셀에는 '가상 데이터'로 표시된다.
"""
from __future__ import annotations

import copy

from . import content as content_mod
from . import records

PERIOD = "2025-12-31"
BINDING = "cash.schedule_recon"
CLS_BINDING = "cash.classification_review"


def _mat(mid, role, name, version, kind="원본", original_id="", receipt="입수", received="2026-01-20",
         confirmed=True, scope="", remaining=""):
    return {"id": mid, "role": role, "name": name, "version_label": version, "kind": kind, "original_id": original_id,
            "provider": "회사 자금팀(가상)", "receipt": receipt, "requested_date": "2026-01-15",
            "received_date": received if receipt == "입수" else "", "as_of_date": PERIOD,
            "location": f"{name}.xlsx", "remaining_work": remaining, "confirmed": confirmed and receipt == "입수",
            "confirmed_by": "작성자" if confirmed and receipt == "입수" else "", "confirmed_date": "2026-01-21" if confirmed and receipt == "입수" else "",
            "confirmed_scope": scope if confirmed and receipt == "입수" else "", "note": ""}


def _row(rid, item, bank, product, sched, sub, sloc, bloc, note=""):
    return {"id": rid, "item_id": item, "name": bank, "product_type": product, "schedule_amount": sched,
            "subledger_amount": sub, "schedule_loc": sloc, "subledger_loc": bloc, "note": note,
            "unusual": False, "unusual_reason": ""}


def _base(resolved):
    d = records.default_data(resolved, PERIOD)
    d["recon"]["sets"][0]["id"] = "s_orig"
    return d


COMMON_FIELDS = {
    "purpose": "현금및현금성자산·장단기금융상품 명세서가 산술적으로 정확하고 예금별 보조원장 및 총계정원장과 일치하는지 확인한다. (가상 사례)",
    "scope": "2025-12-31 현재 명세서 전체 항목. 실재성은 이 조서에서 결론내지 않으며 A-300 실사, A-400 금융기관 조회 조서에서 다룬다. (가상)",
    "risk_ref": "2302 위험평가 조서 현금 항목 (가상 참조)",
    "related_wps": "A-300 현금 실사, A-400 금융기관 조회 (가상 참조)",
}


def normal(resolved):
    d = _base(resolved)
    d["fields"].update(COMMON_FIELDS)
    d["fields"].update({
        "wp_no": "A-200",
        "list_check": "수행 - 누락·추가 없음",
        "list_check_note": "보조원장의 계좌 목록 2건과 명세서 항목 2건을 양방향으로 대조함. 한쪽에만 있는 계좌 없음.",
        "work_performed": "명세서 행별 금액을 재계산하여 표시 합계와 비교하고, 계좌별 금액을 예금별 보조원장 기말잔액과 대사함. 보조원장 합계를 총계정원장 현금및현금성자산 잔액과 비교함.",
        "recon_result": "명세서 재계산 합계 20,500,000원은 표시 합계와 일치함. 계좌별 명세서 금액은 보조원장과 일치하고, 보조원장 합계는 총계정원장 잔액과 일치함.",
        "fs_link_status": "별도 조서 참조",
        "fs_link_ref": "A-100 총괄표 (가상)",
        "fs_link_basis": "재무상태표 현금및현금성자산 20,500,000원 ↔ 총계정원장 잔액, A-100 총괄표 B5행 (가상)",
        "fs_link_statement": "재무상태표의 현금및현금성자산 20,500,000원을 총계정원장 잔액과 대사하여 일치를 확인하였다. 관련 수행 기록은 A-100 총괄표에 기재하였다. (가상)",
        "conclusion": "제공된 자료 범위에서 명세서는 산술적으로 정확하고 보조원장 및 총계정원장과 일치한다. (가상 사례)",
        "procedure_status": "수행 완료", "performer": "작성자", "performed_date": "2026-01-22",
        "review_status": "검토 완료", "reviewer": "검토자(가상)", "review_date": "2026-01-25",
        "review_scope": "조서 전체: 대사표, 자료 확인 기록, 결론",
    })
    d["materials"] = [
        _mat("m_sched", "schedule", "명세_v1", "v1", scope="계좌 목록, 행별 금액, 표시 합계"),
        _mat("m_sub", "subledger", "보조원장", "2025-12-31 마감", scope="K01·K02 기말잔액"),
        _mat("m_gl", "gl", "총계정원장", "2025-12-31 마감", scope="현금및현금성자산 기말잔액"),
    ]
    st = d["recon"]["sets"][0]
    st.update({"schedule_material_id": "m_sched", "stated_total": "20500000", "stated_total_loc": "명세_v1 명세!E6",
               "rows": [_row("r1", "K01", "가나은행(가상)", "보통예금", "12500000", "12500000", "명세_v1 명세!E4", "보조원장 잔액!D4"),
                        _row("r2", "K02", "다라은행(가상)", "정기예금", "8000000", "8000000", "명세_v1 명세!E5", "보조원장 잔액!D5")]})
    d["recon"].update({"gl_balance": "20500000", "gl_loc": "총계정원장 원장!D4", "gl_material_id": "m_gl"})
    d["scan"] = {"status": "수행", "note": "명세서 2개 항목을 확인함. 잔액 0 계좌나 기준일과 다른 기준일의 항목 없음.", "na_reason": ""}
    return d


def difference(resolved):
    d = _base(resolved)
    d["fields"].update(COMMON_FIELDS)
    d["fields"].update({
        "wp_no": "A-200",
        "list_check": "수행 - 누락·추가 없음",
        "list_check_note": "보조원장 계좌 2건과 명세서 항목 2건을 양방향 대조함. 한쪽에만 있는 계좌 없음.",
        "work_performed": "명세서 행별 금액을 재계산하고 계좌별로 보조원장과 대사함. 보조원장 합계를 총계정원장 잔액과 비교함.",
        "recon_result": "명세서 재계산 합계 20,400,000원으로 표시 합계와 100,000원 차이. K01에서 명세서 12,400,000원, 보조원장 12,500,000원으로 100,000원 차이. 보조원장 합계 20,500,000원은 총계정원장과 일치.",
        "fs_link_status": "확인 중",
        "conclusion": "두 차이의 원인을 확인 중이며 미해결 상태다. 재무제표 연결 검토는 아직 수행하지 않았다. (가상 사례)",
        "procedure_status": "진행 중", "performer": "작성자", "performed_date": "",
        "review_status": "미검토",
    })
    d["materials"] = [
        _mat("m_sched", "schedule", "명세_v1", "v1", scope="계좌 목록, 행별 금액, 표시 합계"),
        _mat("m_sub", "subledger", "보조원장", "2025-12-31 마감", scope="K01·K02 기말잔액"),
        _mat("m_gl", "gl", "총계정원장", "2025-12-31 마감", scope="현금및현금성자산 기말잔액"),
    ]
    st = d["recon"]["sets"][0]
    st.update({"schedule_material_id": "m_sched", "stated_total": "20500000", "stated_total_loc": "명세_v1 명세!E6",
               "rows": [_row("r1", "K01", "가나은행(가상)", "보통예금", "12400000", "12500000", "명세_v1 명세!E4", "보조원장 잔액!D4"),
                        _row("r2", "K02", "다라은행(가상)", "정기예금", "8000000", "8000000", "명세_v1 명세!E5", "보조원장 잔액!D5")]})
    d["recon"].update({"gl_balance": "20500000", "gl_loc": "총계정원장 원장!D4", "gl_material_id": "m_gl"})
    d["findings"] = [
        {"id": "f1", "link": "set:s_orig:stated_vs_recalc", "title": "명세서 표시 합계와 재계산 합계 차이", "amount": 100000,
         "fact": "명세서 행별 금액 합계 20,400,000원, 표시 합계 20,500,000원.", "cause": "",
         "explanation_type": "담당자 설명만", "person": "자금팀 담당자(가상)", "discussed_at": "2026-01-22 14:00",
         "explanation": "K01 금액을 옮겨 적을 때 틀렸을 수 있다는 설명. 수정 명세서를 주기로 함.", "recheck_material_id": "",
         "followup": "수정 명세서 요청 (2026-01-22)", "status": "후속 확인 중", "resolution": "", "resolution_basis": ""},
        {"id": "f2", "link": "set:s_orig:row:r1", "title": "K01 명세서와 보조원장 차이", "amount": -100000,
         "fact": "K01 명세서 12,400,000원, 보조원장 12,500,000원.", "cause": "",
         "explanation_type": "없음", "person": "", "discussed_at": "", "explanation": "", "recheck_material_id": "",
         "followup": "보조원장 K01 기말 거래 내역 요청", "status": "미해결", "resolution": "", "resolution_basis": ""},
    ]
    d["scan"] = {"status": "미결정", "note": "", "na_reason": ""}
    return d


def missing(resolved):
    d = _base(resolved)
    d["fields"].update(COMMON_FIELDS)
    d["fields"].update({
        "wp_no": "A-200",
        "list_check": "미수행",
        "work_performed": "원본 명세서로 대사한 뒤 회사가 수정 명세서를 줌. 수정본 기준으로 다시 대사함. K02 보조원장은 아직 받지 못함.",
        "recon_result": "수정 명세서 재계산 합계 20,500,000원은 표시 합계와 일치. K01은 보조원장과 일치. K02 보조원장 미입수로 대사 미완료.",
        "fs_link_status": "미수행",
        "conclusion": "K02 보조원장 미입수로 결론을 내리지 않았다. (가상 사례)",
        "procedure_status": "진행 중", "performer": "작성자", "performed_date": "",
        "review_status": "미검토",
    })
    d["materials"] = [
        _mat("m_sched", "schedule", "명세_v1", "v1", scope="계좌 목록, 행별 금액, 표시 합계"),
        _mat("m_sched2", "schedule", "명세_v2", "v2(수정)", kind="수정본", original_id="m_sched", received="2026-01-24",
             scope="K01 금액 수정 내역, 표시 합계"),
        _mat("m_sub", "subledger", "보조원장_K01", "2025-12-31 마감", scope="K01 기말잔액"),
        _mat("m_sub2", "subledger", "보조원장_K02", "2025-12-31 마감", receipt="요청", confirmed=False,
             remaining="K02 계좌 보조원장 요청(2026-01-22). 받으면 K02 보조부 금액 입력 후 재대사"),
        _mat("m_gl", "gl", "총계정원장", "2025-12-31 마감", scope="현금및현금성자산 기말잔액"),
    ]
    orig = d["recon"]["sets"][0]
    orig.update({"schedule_material_id": "m_sched", "stated_total": "20500000", "stated_total_loc": "명세_v1 명세!E6",
                 "rows": [_row("r1", "K01", "가나은행(가상)", "보통예금", "12400000", "12500000", "명세_v1 명세!E4", "보조원장_K01 잔액!D4"),
                          _row("r2", "K02", "다라은행(가상)", "정기예금", "8000000", "", "명세_v1 명세!E5", "", "보조원장 미입수")]})
    rev = copy.deepcopy(orig)
    rev.update({"id": "s_rev", "label": "수정본 명세서", "schedule_material_id": "m_sched2", "stated_total_loc": "명세_v2 명세!E6"})
    rev["rows"][0].update({"id": "r1b", "schedule_amount": "12500000", "schedule_loc": "명세_v2 명세!E4"})
    rev["rows"][1].update({"id": "r2b", "schedule_loc": "명세_v2 명세!E5"})
    d["recon"]["sets"].append(rev)
    d["recon"].update({"gl_balance": "20500000", "gl_loc": "총계정원장 원장!D4", "gl_material_id": "m_gl"})
    d["findings"] = [
        {"id": "f1", "link": "set:s_orig:stated_vs_recalc", "title": "원본 명세서 표시 합계와 재계산 합계 차이", "amount": 100000,
         "fact": "원본 명세서 행별 합계 20,400,000원, 표시 합계 20,500,000원.", "cause": "K01 금액 기재 오류",
         "explanation_type": "자료로 재확인", "person": "", "discussed_at": "", "explanation": "",
         "recheck_material_id": "m_sched2", "followup": "수정 명세서 입수 후 재계산",
         "status": "처리 완료", "resolution": "수정 명세서(명세_v2)로 재계산한 합계가 표시 합계와 일치함을 확인.",
         "resolution_basis": "명세_v2 명세!E4:E6, 수정본 대사 결과"},
        {"id": "f2", "link": "set:s_orig:row:r1", "title": "원본 명세서 K01과 보조원장 차이", "amount": -100000,
         "fact": "원본 명세서 K01 12,400,000원, 보조원장 12,500,000원.", "cause": "K01 금액 기재 오류",
         "explanation_type": "자료로 재확인", "person": "", "discussed_at": "", "explanation": "",
         "recheck_material_id": "m_sched2", "followup": "",
         "status": "처리 완료", "resolution": "수정 명세서의 K01 12,500,000원이 보조원장과 일치함을 확인.",
         "resolution_basis": "명세_v2 명세!E4, 보조원장_K01 잔액!D4"},
    ]
    return d


def _crow(rid, item, bank, product, amount, aloc, maturity_type, acquired, maturity, tloc,
          restricted, rloc, company, auditor, basis):
    return {"id": rid, "item_id": item, "name": bank, "product_type": product, "amount": amount, "amount_loc": aloc,
            "maturity_type": maturity_type, "acquired_date": acquired, "maturity_date": maturity, "terms_loc": tloc,
            "restricted": restricted, "restriction_note": "", "restriction_loc": rloc,
            "company_class": company, "auditor_class": auditor, "basis": basis, "note": ""}


def classification(resolved):
    """K02 정기예금: 회사는 현금성자산으로 분류, 증서상 취득→만기 181일. 감사인 판단은 가상 예시다."""
    d = records.default_data(resolved, PERIOD)
    d["fields"].update({
        "wp_no": "A-210",
        "purpose": resolved.get("sample_purpose", "") or "명세서 항목별 분류가 증서·약정서의 만기와 사용제한 약정에 비추어 적절한지 확인한다. (가상 사례)",
        "scope": "2025-12-31 현재 명세서 전체 항목(K01·K02). 금액 대사는 A-200, 사용제한 조회는 A-400에서 다루고 여기서는 참조만 한다. (가상)",
        "risk_ref": "2302 위험평가 조서 현금 항목 (가상 참조)",
        "related_wps": "A-200 명세서 대사, A-400 금융기관 조회 (가상 참조)",
        "work_performed": "명세서의 항목별 회사 분류를 옮겨 적고, K02 예금증서에서 가입일과 만기일을 확인함. 사용제한 여부는 A-400 금융기관 조회 회신의 담보·제한 기재란으로 확인함.",
        "classify_result": "K01 보통예금은 회사 분류와 판단이 같음. K02 정기예금 8,000,000원은 회사가 현금및현금성자산으로 분류했으나 증서상 취득일부터 만기일까지 181일이어서 단기금융상품으로 판단함. 재분류 금액 8,000,000원.",
        "conclusion": "K02 분류 차이는 회사 설명의 근거(중도해지 조건) 자료를 받지 못해 미해결 상태다. (가상 사례)",
        "procedure_status": "진행 중", "performer": "작성자", "performed_date": "",
        "review_status": "미검토",
    })
    d["materials"] = [
        _mat("m_sched", "schedule", "명세_v1", "v1", scope="항목 목록, 금액, 회사 분류"),
        _mat("m_terms", "terms", "예금증서_K02", "증서 사본", scope="K02 가입일·만기일·금액·중도해지 조건"),
        dict(_mat("m_restr", "restriction", "금융기관 조회 회신(A-400)", "회신 요약", scope="K01·K02 담보·사용제한 기재란"),
             location="A-400 금융기관 조회 조서 회신 요약 (가상)"),
    ]
    d["classify"] = {"schedule_material_id": "m_sched", "rows": [
        _crow("c1", "K01", "가나은행(가상)", "보통예금", "12400000", "명세_v1 명세!E4", "만기 없음", "", "", "",
              "없음", "A-400 회신 K01 담보란", "현금및현금성자산", "현금및현금성자산", "요구불예금, 사용제한 없음"),
        _crow("c2", "K02", "다라은행(가상)", "정기예금", "8000000", "명세_v1 명세!E5", "만기 있음", "2025-11-15", "2026-05-15",
              "예금증서_K02 증서!C5:C6", "없음", "A-400 회신 K02 담보란", "현금및현금성자산", "단기금융상품",
              "증서상 취득일부터 만기일까지 181일"),
    ]}
    d["findings"] = [
        {"id": "f1", "link": "cls:row:c2", "title": "K02 분류 차이: 회사 현금및현금성자산 → 감사인 판단 단기금융상품", "amount": 8000000,
         "fact": "K02 정기예금 8,000,000원. 예금증서상 가입일 2025-11-15, 만기일 2026-05-15(181일). 회사는 현금및현금성자산으로 분류.",
         "cause": "", "explanation_type": "담당자 설명만", "person": "자금팀 담당자(가상)", "discussed_at": "2026-01-23 10:00",
         "explanation": "언제든 중도해지할 수 있어 현금성자산으로 봤다는 설명. 중도해지 조건이 적힌 약관을 주기로 함.",
         "recheck_material_id": "", "followup": "K02 상품 약관(중도해지 조건) 요청 (2026-01-23). 받으면 조건 확인 후 판단 재검토",
         "status": "후속 확인 중", "resolution": "", "resolution_basis": ""},
    ]
    return d


def _acct(code, name, fs_line, prior, unadjusted):
    return {"code": code, "name": name, "fs_line": fs_line, "prior": prior, "unadjusted": unadjusted, "loc": ""}


def _fs(statement, category, name, prior, current):
    return {"statement": statement, "category": category, "name": name, "prior": prior, "current": current, "loc": ""}


def _je(je_no, date, desc, lines, kind="일반"):
    """lines: [(계정코드, 차변, 대변)]"""
    return [{"id": f"{je_no}-{i}", "je_no": je_no, "line": i, "date": date, "code": code, "description": desc,
             "debit": dr, "credit": cr, "kind": kind} for i, (code, dr, cr) in enumerate(lines, 1)]


def ledger():
    """가상 차이(주)의 회사 재무제표·시산표(감사 전), 가상 분개장, 감사인 수정분개.

    금액은 계정의 정상 잔액 방향 기준 양수. 손익 계정의 전기말 열은 전기 금액(비교용).
    보통예금(K01)·정기예금(K02) 당기 잔액은 명세서 대사의 보조원장·총계정원장(합계 20,500,000)과 같고,
    정기예금 가입(J006, 2025-11-15)은 분류 검토 A-210의 예금증서 가입일과 같다.
    회사 재무제표는 시산표(수정 전)와 일치하고, 감사인 수정분개 A001(미지급 급여 300,000)로 수정후 금액이 달라진다.
    """
    fs = [
        _fs("재무상태표", "자산", "현금및현금성자산", 15_000_000, 20_500_000),
        _fs("재무상태표", "자산", "매출채권", 15_000_000, 18_000_000),
        _fs("재무상태표", "부채", "매입채무", 6_000_000, 7_500_000),
        _fs("재무상태표", "부채", "기타유동부채", 0, 0),
        _fs("재무상태표", "자본", "자본금", 10_000_000, 10_000_000),
        _fs("재무상태표", "자본", "이익잉여금", 14_000_000, 21_000_000),
        _fs("손익계산서", "수익", "매출액", 25_000_000, 30_000_000),
        _fs("손익계산서", "비용", "매출원가", 17_000_000, 20_000_000),
        _fs("손익계산서", "비용", "판매비와관리비", 3_000_000, 3_000_000),
    ]
    accounts = [
        _acct("10301", "보통예금", "현금및현금성자산", 15_000_000, 12_500_000),
        _acct("10302", "정기예금", "현금및현금성자산", 0, 8_000_000),
        _acct("10800", "외상매출금", "매출채권", 15_000_000, 18_000_000),
        _acct("25100", "외상매입금", "매입채무", 6_000_000, 7_500_000),
        _acct("26200", "미지급비용", "기타유동부채", 0, 0),
        _acct("33100", "자본금", "자본금", 10_000_000, 10_000_000),
        _acct("37500", "이월이익잉여금", "이익잉여금", 14_000_000, 14_000_000),
        _acct("40100", "상품매출", "매출액", 25_000_000, 30_000_000),
        _acct("45100", "상품매출원가", "매출원가", 17_000_000, 20_000_000),
        _acct("80100", "급여", "판매비와관리비", 3_000_000, 3_000_000),
    ]
    journal = (
        _je("J001", "2025-03-15", "상품 외상 매출 (가상)", [("10800", 30_000_000, 0), ("40100", 0, 30_000_000)])
        + _je("J002", "2025-04-10", "외상매출금 회수 (가상)", [("10301", 27_000_000, 0), ("10800", 0, 27_000_000)])
        + _je("J003", "2025-05-20", "상품 외상 매입·매출원가 대체 (가상)", [("45100", 20_000_000, 0), ("25100", 0, 20_000_000)])
        + _je("J004", "2025-06-30", "외상매입금 지급 (가상)", [("25100", 18_500_000, 0), ("10301", 0, 18_500_000)])
        + _je("J005", "2025-09-01", "급여 지급 (가상)", [("80100", 3_000_000, 0), ("10301", 0, 3_000_000)])
        + _je("J006", "2025-11-15", "정기예금 가입 K02 (가상)", [("10302", 8_000_000, 0), ("10301", 0, 8_000_000)])
    )
    adjustments = [
        {"id": "a1", "je_no": "A001", "date": "2025-12-31", "description": "12월 급여 미지급 계상 (가상 감사인 수정분개)",
         "lines": [{"code": "80100", "debit": 300_000, "credit": ""}, {"code": "26200", "debit": "", "credit": 300_000}]},
    ]
    return {"fs": fs, "accounts": accounts, "journal": journal, "adjustments": adjustments, "net_income_line": "이익잉여금"}


# 정산표·분개장을 넣을 회사와, 그 회사 조서가 참조할 계정과목
LEDGER_CASES = {"가상 차이(주)": ["10301", "10302"]}

CASES = [
    ("가상 정상(주)", normal),
    ("가상 차이(주)", difference),
    ("가상 자료부족(주)", missing),
]
# 분류 검토 사례는 대사 사례와 같은 회사·감사건에 조서를 하나 더 만든다
CLASSIFICATION_CASES = [
    ("가상 차이(주)", classification),
]


def seed() -> list[int]:
    """대사 사례 3종 조서 id 뒤에 분류 검토 사례 조서 id를 붙여 돌려준다."""
    resolved = content_mod.resolve(BINDING)
    ids, engagements = [], {}
    for name, builder in CASES:
        cid = records.create_company(name, is_sample=True)
        eid = records.create_engagement(cid, PERIOD)
        engagements[name] = eid
        if name in LEDGER_CASES:
            records.save_ledger(eid, ledger(), source="가상 데이터")
        wid = records.create_workpaper(eid, BINDING)
        records.save_workpaper(wid, _link(builder(resolved), name), base_rev=1, note="가상 사례 입력")
        ids.append(wid)
    cls_resolved = content_mod.resolve(CLS_BINDING)
    for name, builder in CLASSIFICATION_CASES:
        wid = records.create_workpaper(engagements[name], CLS_BINDING)
        records.save_workpaper(wid, _link(builder(cls_resolved), name), base_rev=1, note="가상 사례 입력")
        ids.append(wid)
    return ids


def _link(data: dict, company: str) -> dict:
    if company in LEDGER_CASES:
        data["linked_accounts"] = list(LEDGER_CASES[company])
    return data
