"""계산·분기·상태 엔진.

계산은 이 모듈 한 곳에서만 한다. 화면은 preview 결과를 받아 표시하고,
엑셀은 같은 계산을 수식으로 쓴 뒤 테스트에서 이 모듈의 값과 대조한다.

원칙
- 빈칸은 '확인하지 않음'이다. 0원으로 계산하지 않는다.
- 프로그램은 차이를 계산하고 기록할 자리를 연다. 원인·영향·결론은 판단하지 않는다.
"""
from __future__ import annotations

import re
from typing import Any

# 콘텐츠가 참조할 수 있는 식별자. 콘텐츠 검증(content.py)이 이 목록으로 확인한다.
CALCS = {"row_diff", "recalc_total", "stated_vs_recalc", "subledger_total", "subledger_vs_gl"}
CHECKS = {
    "required_fields", "materials_status", "materials_confirmed", "recon_blanks",
    "diff_without_finding", "list_check_finding", "findings_open", "findings_resolution",
    "findings_explanation_only", "assertion_change_reason", "scan_undecided",
    "review_state", "status_consistency",
}
COMPONENTS = {"fields", "assertions", "materials", "recon", "scan", "findings", "open_items", "review_comments"}
FIELD_TYPES = {"text", "textarea", "date", "choice", "amount"}

MATERIAL_ROLES = ["schedule", "subledger", "gl", "other"]
REQUIRED_ROLES = ["schedule", "subledger", "gl"]
RECEIPT = ["요청 전", "요청", "입수", "입수 불가"]
FINDING_STATUS = ["미해결", "후속 확인 중", "처리 완료"]
EXPLANATION = ["없음", "담당자 설명만", "자료로 재확인"]

_AMOUNT_RE = re.compile(r"^-?\d+$")


# ---------------------------------------------------------------- 금액
def parse_amount(raw: Any) -> tuple[int | None, str | None]:
    """(값, 오류). 빈칸은 (None, None). 정수 원 단위만 받는다."""
    if raw is None:
        return None, None
    if isinstance(raw, bool):
        return None, "숫자가 아님"
    if isinstance(raw, int):
        return raw, None
    if isinstance(raw, float):
        return (int(raw), None) if raw.is_integer() else (None, "원 단위 정수만 입력")
    s = str(raw).strip().replace(",", "").replace(" ", "")
    if s == "":
        return None, None
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    if not _AMOUNT_RE.match(s):
        return None, "숫자가 아님" if not re.match(r"^-?\d+\.\d+$", s) else "원 단위 정수만 입력"
    return int(s), None


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip() == "")


# ---------------------------------------------------------------- 표시 조건
def eval_cond(cond: dict | None, fields: dict) -> bool:
    if not cond:
        return True
    v = fields.get(cond["field"])
    if "eq" in cond:
        return v == cond["eq"]
    if "in" in cond:
        return v in cond["in"]
    if cond.get("not_empty"):
        return not _blank(v)
    raise ValueError(f"지원하지 않는 조건: {cond}")


def iter_fields(content: dict):
    for step in content["steps"]:
        for comp in step["components"]:
            if comp["type"] == "fields":
                for f in comp["fields"]:
                    yield step, f


# ---------------------------------------------------------------- 대사 계산
def compute_set(rec_set: dict, gl_raw: Any) -> dict:
    """한 대사 세트(명세서 버전 하나)의 계산."""
    rows_out = {}
    sched_vals, sub_vals = [], []
    sched_blank = sub_blank = 0
    errors = []
    for row in rec_set.get("rows", []):
        s, se = parse_amount(row.get("schedule_amount"))
        b, be = parse_amount(row.get("subledger_amount"))
        if se:
            errors.append((row["id"], "schedule_amount", se))
        if be:
            errors.append((row["id"], "subledger_amount", be))
        diff = s - b if (s is not None and b is not None) else None
        rows_out[row["id"]] = {"schedule": s, "subledger": b, "diff": diff,
                               "missing": [k for k, v in (("명세서", s), ("보조부", b)) if v is None]}
        if s is None:
            sched_blank += 1
        else:
            sched_vals.append(s)
        if b is None:
            sub_blank += 1
        else:
            sub_vals.append(b)
    n = len(rec_set.get("rows", []))
    recalc = sum(sched_vals) if n and sched_blank == 0 else None
    sub_total = sum(sub_vals) if n and sub_blank == 0 else None
    stated, ste = parse_amount(rec_set.get("stated_total"))
    if ste:
        errors.append(("_set", "stated_total", ste))
    gl, gle = parse_amount(gl_raw)
    if gle:
        errors.append(("_set", "gl_balance", gle))
    return {
        "rows": rows_out,
        "row_count": n,
        "schedule_blank": sched_blank,
        "subledger_blank": sub_blank,
        "recalc_total": recalc,
        "stated_total": stated,
        "stated_vs_recalc": (stated - recalc) if (stated is not None and recalc is not None) else None,
        "subledger_total": sub_total,
        "gl_balance": gl,
        "subledger_vs_gl": (sub_total - gl) if (sub_total is not None and gl is not None) else None,
        "errors": errors,
    }


def diff_points(data: dict, calc_sets: dict) -> list[dict]:
    """0이 아닌 차이 목록. 각 항목은 발견 사항과 연결할 키를 갖는다."""
    out = []
    for st in data["recon"]["sets"]:
        c = calc_sets[st["id"]]
        label = st.get("label") or st["id"]
        if c["stated_vs_recalc"] not in (None, 0):
            out.append({"key": f"set:{st['id']}:stated_vs_recalc", "set": st["id"],
                        "title": f"[{label}] 명세서 표시 합계와 재계산 합계 차이", "amount": c["stated_vs_recalc"]})
        for row in st.get("rows", []):
            d = c["rows"][row["id"]]["diff"]
            if d not in (None, 0):
                out.append({"key": f"set:{st['id']}:row:{row['id']}", "set": st["id"], "row": row["id"],
                            "title": f"[{label}] {row.get('item_id') or '(식별값 없음)'} 명세서와 보조부 차이",
                            "amount": d})
        if c["subledger_vs_gl"] not in (None, 0):
            out.append({"key": f"set:{st['id']}:subledger_vs_gl", "set": st["id"],
                        "title": f"[{label}] 보조부 합계와 총계정원장 잔액 차이", "amount": c["subledger_vs_gl"]})
    return out


# ---------------------------------------------------------------- 전체 계산
def compute(content: dict, data: dict) -> dict:
    fields = data.get("fields", {})
    visible = {f["key"]: eval_cond(f.get("show_if"), fields) for _, f in iter_fields(content)}

    recon = data["recon"]
    calc_sets = {st["id"]: compute_set(st, recon.get("gl_balance")) for st in recon["sets"]}
    active_id = recon["sets"][-1]["id"] if recon["sets"] else None
    diffs = diff_points(data, calc_sets)
    linked = {f.get("link") for f in data.get("findings", []) if f.get("link")}
    for d in diffs:
        d["has_finding"] = d["key"] in linked

    ui = {
        "materials": {m["id"]: {"show_original": m.get("kind") == "수정본",
                                "show_remaining": m.get("receipt") != "입수",
                                "show_confirm": m.get("receipt") == "입수"} for m in data.get("materials", [])},
        "findings": {f["id"]: {"show_person": f.get("explanation_type") == "담당자 설명만",
                               "show_material": f.get("explanation_type") == "자료로 재확인",
                               "show_resolution": f.get("status") == "처리 완료",
                               "link_state": _link_state(f.get("link"), diffs, data)} for f in data.get("findings", [])},
        "scan": {"show_note": (data.get("scan", {}).get("status") == "수행"),
                 "show_reason": (data.get("scan", {}).get("status") == "해당 없음")},
        "assertion_changed": sorted(data["assertions"].get("applied", [])) != sorted(content["assertions"]["default"]),
        "unused_revised_schedules": _unused_revised(data),
        "show_findings_hint": bool(diffs),
    }

    items = run_checks(content, data, visible, calc_sets, diffs)
    findings = data.get("findings", [])
    f_counts = {s: sum(1 for f in findings if f.get("status") == s) for s in FINDING_STATUS}
    if not findings:
        f_summary = "발견 사항 없음"
    elif f_counts["처리 완료"] == len(findings):
        f_summary = f"{len(findings)}건 모두 처리 완료"
    else:
        f_summary = f"미처리 {len(findings) - f_counts['처리 완료']}건 / 전체 {len(findings)}건"
    blocks = [i for i in items if i["level"] == "block"]
    return {
        "visible": visible,
        "sets": calc_sets,
        "active_set": active_id,
        "diffs": diffs,
        "ui": ui,
        "open_items": items,
        "status": {
            "procedure": fields.get("procedure_status") or "미착수",
            "procedure_ready": len(blocks) == 0,
            "blocking_count": len(blocks),
            "findings": f_summary,
            "findings_counts": f_counts,
            "findings_unresolved": len(findings) - f_counts["처리 완료"],
            "review": fields.get("review_status") or "미검토",
        },
        "step_counts": _step_counts(content, items),
    }


def _link_state(link, diffs, data) -> str:
    """발견 사항이 가리키는 차이의 현재 상태: 차이 있음 / 차이 없어짐 / 수동 등록."""
    if not link or not str(link).startswith("set:"):
        return "manual"
    if any(d["key"] == link for d in diffs):
        return "open"
    sid = str(link).split(":")[1]
    if not any(st["id"] == sid for st in data["recon"]["sets"]):
        return "missing"
    return "zero_or_blank"


def _unused_revised(data: dict) -> list[str]:
    used = {st.get("schedule_material_id") for st in data["recon"]["sets"]}
    return [m["id"] for m in data.get("materials", [])
            if m.get("role") == "schedule" and m.get("kind") == "수정본" and m["id"] not in used]


def _step_counts(content: dict, items: list[dict]) -> dict:
    out = {s["id"]: {"block": 0, "warn": 0, "info": 0} for s in content["steps"]}
    for i in items:
        if i.get("step") in out:
            out[i["step"]][i["level"]] += 1
    return out


# ---------------------------------------------------------------- 점검(남은 작업)
def _item(level, category, step, message, ref=None):
    return {"level": level, "category": category, "step": step, "message": message, "ref": ref}


def run_checks(content, data, visible, calc_sets, diffs) -> list[dict]:
    fields = data.get("fields", {})
    enabled = set(content.get("checks", []))
    items: list[dict] = []
    mats = data.get("materials", [])
    mat_by_id = {m["id"]: m for m in mats}
    labels = content.get("documents", {})
    findings = data.get("findings", [])

    if "required_fields" in enabled:
        for step, f in iter_fields(content):
            if f.get("required") and visible.get(f["key"], True) and _blank(fields.get(f["key"])):
                items.append(_item("block", "미입력", step["id"], f"{f['label']} 미입력", f"field:{f['key']}"))
            if f["type"] == "amount" and visible.get(f["key"], True):
                _, err = parse_amount(fields.get(f["key"]))
                if err:
                    items.append(_item("block", "미입력", step["id"], f"{f['label']}: {err}", f"field:{f['key']}"))

    if "materials_status" in enabled:
        for role in REQUIRED_ROLES:
            if not any(m.get("role") == role for m in mats):
                items.append(_item("block", "자료", "materials", f"자료 미등록: {labels.get(role, role)}"))
        for m in mats:
            name = m.get("name") or "(이름 없음)"
            if _blank(m.get("name")):
                items.append(_item("block", "미입력", "materials", "자료명이 비어 있는 자료가 있음", f"material:{m['id']}"))
            if m.get("receipt") != "입수":
                msg = f"미입수 자료: {name} ({m.get('receipt') or '상태 미입력'})"
                if _blank(m.get("remaining_work")):
                    msg += " — 남은 작업 미기록"
                items.append(_item("block", "자료", "materials", msg, f"material:{m['id']}"))
            if m.get("kind") == "수정본" and not m.get("original_id"):
                items.append(_item("block", "자료", "materials", f"수정본 '{name}'에 원본 자료가 연결되지 않음", f"material:{m['id']}"))
        for mid in _unused_revised(data):
            items.append(_item("block", "자료", "recon",
                               f"수정본 명세서 '{mat_by_id[mid].get('name')}' 입수 — 수정본 기준 재대사 기록 없음", f"material:{mid}"))

    if "materials_confirmed" in enabled:
        for m in mats:
            if m.get("receipt") != "입수":
                continue
            name = m.get("name") or "(이름 없음)"
            if not m.get("confirmed"):
                items.append(_item("warn", "자료", "materials", f"'{name}': 등록만 되어 있고 증거 확인 기록 없음", f"material:{m['id']}"))
            else:
                missing = [lab for k, lab in (("confirmed_by", "확인자"), ("confirmed_date", "확인일"), ("confirmed_scope", "확인 범위")) if _blank(m.get(k))]
                if missing:
                    items.append(_item("block", "미입력", "materials", f"'{name}' 증거 확인 기록에 {', '.join(missing)} 없음", f"material:{m['id']}"))

    if "recon_blanks" in enabled:
        # 미입력 점검은 현재(마지막) 대사 세트에만 한다. 이전 세트는 수정 전 기록으로 보존된다.
        for st in data["recon"]["sets"][-1:]:
            c = calc_sets[st["id"]]
            label = st.get("label") or st["id"]
            if c["row_count"] == 0:
                items.append(_item("block", "미입력", "recon", f"[{label}] 대사 항목이 없음"))
            if c["schedule_blank"]:
                items.append(_item("block", "미입력", "recon", f"[{label}] 명세서 금액 미입력 {c['schedule_blank']}건 — 재계산 합계를 계산하지 않음"))
            if c["subledger_blank"]:
                items.append(_item("block", "미입력", "recon", f"[{label}] 보조부 금액 미입력 {c['subledger_blank']}건 — 보조부 합계를 계산하지 않음"))
            if c["stated_total"] is None:
                items.append(_item("block", "미입력", "recon", f"[{label}] 명세서 표시 합계 미입력"))
            if _blank(st.get("schedule_material_id")):
                items.append(_item("warn", "자료", "recon", f"[{label}] 대사에 쓴 명세서 자료가 연결되지 않음"))
            for row in st.get("rows", []):
                if _blank(row.get("item_id")):
                    items.append(_item("block", "미입력", "recon", f"[{label}] 식별값이 없는 대사 항목이 있음", f"row:{row['id']}"))
                for k, lab in (("schedule_loc", "명세서 근거 위치"), ("subledger_loc", "보조부 근거 위치")):
                    if _blank(row.get(k)):
                        items.append(_item("warn", "미입력", "recon", f"[{label}] {row.get('item_id') or '(식별값 없음)'}: {lab} 없음", f"row:{row['id']}"))
                if row.get("unusual") and _blank(row.get("unusual_reason")):
                    items.append(_item("block", "미입력", "recon", f"[{label}] {row.get('item_id')}: 비경상 표시 이유 없음", f"row:{row['id']}"))
            for rid, fld, err in c["errors"]:
                items.append(_item("block", "미입력", "recon", f"[{label}] 금액 형식 오류({err})", f"row:{rid}"))
        if parse_amount(data["recon"].get("gl_balance"))[0] is None:
            items.append(_item("block", "미입력", "recon", "총계정원장 잔액 미입력"))

    if "diff_without_finding" in enabled:
        for d in diffs:
            if not d["has_finding"]:
                items.append(_item("block", "차이·발견사항", "findings",
                                   f"{d['title']} {d['amount']:,}원 — 발견 사항 기록 없음", d["key"]))

    if "list_check_finding" in enabled and fields.get("list_check") == "미수행":
        items.append(_item("block", "미입력", "recon", "명세서·보조부 항목 목록 양방향 대조 미수행"))
    if "list_check_finding" in enabled and fields.get("list_check") == "수행 - 누락·추가 있음":
        if not any(f.get("link") == "list_check" for f in findings):
            items.append(_item("block", "차이·발견사항", "findings", "목록 대조에서 누락·추가 항목 확인 — 발견 사항 기록 없음", "list_check"))

    if "findings_open" in enabled:
        for f in findings:
            if f.get("status") != "처리 완료":
                items.append(_item("block", "차이·발견사항", "findings",
                                   f"미해결: {f.get('title') or '(제목 없음)'} ({f.get('status') or '상태 미입력'})", f"finding:{f['id']}"))

    if "findings_resolution" in enabled:
        for f in findings:
            if f.get("status") == "처리 완료" and (_blank(f.get("resolution")) or _blank(f.get("resolution_basis"))):
                items.append(_item("block", "차이·발견사항", "findings",
                                   f"'{f.get('title')}' 처리 완료로 표시했으나 처리 내용·근거 미기록", f"finding:{f['id']}"))
            if f.get("explanation_type") == "담당자 설명만":
                miss = [lab for k, lab in (("person", "상대자"), ("discussed_at", "일시"), ("explanation", "설명 내용")) if _blank(f.get(k))]
                if miss:
                    items.append(_item("block", "미입력", "findings", f"'{f.get('title')}' 담당자 설명의 {', '.join(miss)} 미기록", f"finding:{f['id']}"))
            if f.get("explanation_type") == "자료로 재확인" and _blank(f.get("recheck_material_id")):
                items.append(_item("block", "미입력", "findings", f"'{f.get('title')}' 재확인에 쓴 자료가 연결되지 않음", f"finding:{f['id']}"))

    if "findings_explanation_only" in enabled:
        for f in findings:
            if f.get("status") == "처리 완료" and f.get("explanation_type") in (None, "", "없음", "담당자 설명만"):
                items.append(_item("warn", "차이·발견사항", "findings",
                                   f"'{f.get('title')}' 자료 재확인 없이 처리 완료로 표시됨 (담당자 설명만으로는 적절한 근거가 되지 못함)", f"finding:{f['id']}"))

    if "assertion_change_reason" in enabled:
        a = data["assertions"]
        if sorted(a.get("applied", [])) != sorted(content["assertions"]["default"]):
            if _blank(a.get("change_reason")):
                items.append(_item("block", "미입력", "purpose", "적용 경영진 주장을 콘텐츠 기본값과 다르게 바꿨으나 변경 이유 없음"))
        if not a.get("applied"):
            items.append(_item("block", "미입력", "purpose", "적용한 경영진 주장이 없음"))

    if "scan_undecided" in enabled:
        sc = data.get("scan", {})
        st = sc.get("status") or "미결정"
        if st == "미결정":
            items.append(_item("info", "선택 단계", "recon", "명세서 스캔(선택 단계) 수행 여부 미결정"))
        elif st == "수행" and _blank(sc.get("note")):
            items.append(_item("block", "미입력", "recon", "명세서 스캔 수행 내용 미기록"))
        elif st == "해당 없음" and _blank(sc.get("na_reason")):
            items.append(_item("block", "미입력", "recon", "명세서 스캔을 하지 않은 이유 미기록"))

    if "review_state" in enabled:
        rs = fields.get("review_status") or "미검토"
        if rs == "미검토":
            items.append(_item("info", "검토", "review", "미검토 — 출력물에 미검토로 표시됨"))
        if rs == "검토 완료":
            miss = [lab for k, lab in (("reviewer", "검토자"), ("review_date", "검토일"), ("review_scope", "검토 범위")) if _blank(fields.get(k))]
            if miss:
                items.append(_item("block", "검토", "review", f"검토 완료로 표시했으나 {', '.join(miss)} 없음"))
            if any(not c.get("resolved") for c in data.get("review_comments", [])):
                items.append(_item("block", "검토", "review", "검토 완료로 표시했으나 처리되지 않은 검토 의견이 있음"))
        for c in data.get("review_comments", []):
            if not c.get("resolved") and rs != "검토 완료":
                items.append(_item("warn", "검토", "review", f"처리되지 않은 검토 의견: {(c.get('text') or '')[:30]}", f"comment:{c['id']}"))

    if "status_consistency" in enabled:
        blocks = [i for i in items if i["level"] == "block"]
        if fields.get("procedure_status") == "수행 완료" and blocks:
            items.append(_item("warn", "주의", "review", f"수행 완료로 표시했으나 완료되지 않은 항목 {len(blocks)}건"))
        if fields.get("review_status") == "검토 완료" and fields.get("procedure_status") not in ("수행 완료", "해당 없음", "대체절차 수행"):
            items.append(_item("warn", "주의", "review", "검토 완료로 표시했으나 절차 수행 상태가 완료가 아님"))
    return items
