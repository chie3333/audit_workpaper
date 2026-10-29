"""계산·분기·상태 엔진.

계산은 이 모듈 한 곳에서만 한다. 화면은 preview 결과를 받아 표시하고,
엑셀은 같은 계산을 수식으로 쓴 뒤 테스트에서 이 모듈의 값과 대조한다.

원칙
- 빈칸은 '확인하지 않음'이다. 0원으로 계산하지 않는다.
- 프로그램은 차이를 계산하고 기록할 자리를 연다. 원인·영향·결론은 판단하지 않는다.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

# 콘텐츠가 참조할 수 있는 식별자. 콘텐츠 검증(content.py)이 이 목록으로 확인한다.
CALCS = {"row_diff", "recalc_total", "stated_vs_recalc", "subledger_total", "subledger_vs_gl",
         "term_days", "class_totals", "reclass_diff"}
CHECKS = {
    "required_fields", "materials_status", "materials_confirmed", "recon_blanks",
    "diff_without_finding", "list_check_finding", "findings_open", "findings_resolution",
    "findings_explanation_only", "assertion_change_reason", "scan_undecided",
    "review_state", "status_consistency", "classify_blanks", "ledger_link",
}
COMPONENTS = {"fields", "assertions", "materials", "accounts", "recon", "scan", "classify", "findings", "open_items", "review_comments"}
FIELD_TYPES = {"text", "textarea", "date", "choice", "amount"}

MATERIAL_ROLES = ["schedule", "subledger", "gl", "other"]
REQUIRED_ROLES = ["schedule", "subledger", "gl"]  # 템플릿이 required_documents를 정하지 않으면 이 목록
RECEIPT = ["요청 전", "요청", "입수", "입수 불가"]
FINDING_STATUS = ["미해결", "후속 확인 중", "처리 완료"]
EXPLANATION = ["없음", "담당자 설명만", "자료로 재확인"]
MATURITY = ["만기 있음", "만기 없음"]
# 정산표 계정 분류별 정상 잔액 방향. 차변 쪽은 +1, 대변 쪽은 -1 (정산표 금액은 정상 잔액 방향의 양수로 적는다)
CATEGORY_SIDE = {"자산": 1, "비용": 1, "부채": -1, "자본": -1, "수익": -1}
TB_COLUMNS = ["prior", "unadjusted", "adjustment", "adjusted"]
JE_KINDS = ["일반", "수정분개"]
RESTRICTION = ["미확인", "없음", "있음"]

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


def parse_date(raw: Any) -> tuple[date | None, str | None]:
    """(날짜, 오류). 빈칸은 (None, None). YYYY-MM-DD만 받는다."""
    if _blank(raw):
        return None, None
    if isinstance(raw, date):
        return raw, None
    try:
        return datetime.strptime(str(raw).strip(), "%Y-%m-%d").date(), None
    except ValueError:
        return None, "날짜 형식은 YYYY-MM-DD"


def required_roles(content: dict) -> list[str]:
    return content.get("required_documents", REQUIRED_ROLES)


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


# ---------------------------------------------------------------- 분류 검토 계산
def compute_classify(cls: dict, as_of_raw: Any, classes: list[str]) -> dict:
    """분류 검토표 계산. 기간(일수)과 분류별 합계·차이만 계산하고 분류는 판단하지 않는다.

    - 취득→만기, 기준일→만기 일수. 만기 없음이면 계산하지 않는다(None).
    - 재분류 금액: 회사 분류와 감사인 판단 분류가 다르면 그 행의 금액, 같으면 0. 하나라도 비면 None.
    - 분류별 합계: 금액이나 분류가 빈 행이 하나라도 있으면 계산하지 않는다.
    """
    as_of, _ = parse_date(as_of_raw)
    rows_out, errors = {}, []
    amounts, comp_cls, aud_cls = [], [], []
    for row in cls.get("rows", []):
        amt, ae = parse_amount(row.get("amount"))
        if ae:
            errors.append((row["id"], "amount", ae))
        acq, de1 = parse_date(row.get("acquired_date"))
        mat, de2 = parse_date(row.get("maturity_date"))
        for k, e in (("acquired_date", de1), ("maturity_date", de2)):
            if e:
                errors.append((row["id"], k, e))
        no_maturity = row.get("maturity_type") == "만기 없음"
        acq_days = (mat - acq).days if (not no_maturity and acq and mat) else None
        remain_days = (mat - as_of).days if (not no_maturity and mat and as_of) else None
        c, a = (row.get("company_class") or "").strip(), (row.get("auditor_class") or "").strip()
        reclass = None if (amt is None or not c or not a) else (0 if c == a else amt)
        rows_out[row["id"]] = {"amount": amt, "acq_days": acq_days, "remain_days": remain_days,
                               "no_maturity": no_maturity, "company": c, "auditor": a, "reclass": reclass,
                               "date_order_error": bool(acq and mat and mat < acq)}
        amounts.append(amt)
        comp_cls.append(c)
        aud_cls.append(a)
    n = len(amounts)
    amounts_ok = n > 0 and all(v is not None for v in amounts)
    comp_ok = amounts_ok and all(comp_cls)
    aud_ok = amounts_ok and all(aud_cls)
    totals = {}
    for k in classes:
        ct = sum(v for v, c in zip(amounts, comp_cls) if c == k) if comp_ok else None
        at = sum(v for v, c in zip(amounts, aud_cls) if c == k) if aud_ok else None
        totals[k] = {"company": ct, "auditor": at, "diff": (at - ct) if (ct is not None and at is not None) else None}
    return {
        "rows": rows_out,
        "row_count": n,
        "total_amount": sum(amounts) if amounts_ok else None,
        "totals": totals,
        "unknown_classes": sorted({c for c in comp_cls + aud_cls if c and c not in classes}),
        "errors": errors,
    }


def classify_diffs(data: dict, calc: dict | None) -> list[dict]:
    """회사 분류와 감사인 판단 분류가 다른 행. 발견 사항과 연결할 키를 갖는다."""
    if not calc:
        return []
    out = []
    for row in data["classify"].get("rows", []):
        c = calc["rows"][row["id"]]
        if c["reclass"] not in (None, 0):
            out.append({"key": f"cls:row:{row['id']}", "row": row["id"],
                        "title": f"{row.get('item_id') or '(식별값 없음)'} 분류 차이: 회사 {c['company']} → 감사인 판단 {c['auditor']}",
                        "amount": c["reclass"]})
    return out


# ---------------------------------------------------------------- 정산표·재무제표·원장·분개장
def _sum(vals):
    """하나라도 None이면 None. 빈칸을 0으로 보지 않는다."""
    vals = list(vals)
    return None if any(v is None for v in vals) else sum(vals)


def _sub(a, b):
    return None if a is None or b is None else a - b


def change_rate(change, prior):
    """증감률(%) = 증감액 ÷ |전기|. 전기가 0이거나 빈칸이면 계산하지 않는다(None). 소수 첫째 자리."""
    if change is None or not prior:
        return None
    return round(change / abs(prior) * 100, 1)


def compute_ledger(ledger: dict) -> dict:
    """정산표·분개장 계산. 정산표 금액은 계정의 정상 잔액 방향 기준 양수다.

    - 계정별: 변동 = 수정후 − 전기말, 수정후 − (수정전 + 수정분개)
    - 분개장 대조: 기초(재무상태표 계정은 전기말, 손익 계정은 0) + 일반 분개 = 수정전, 수정분개 합 = 수정분개
    - 재무제표: 표시 항목별 합계. 손익 계정의 전기말 열은 전기 금액(비교용)이다.
      당기순이익은 net_income_line(예: 이익잉여금) 당기 금액에 더한다.
    """
    accts = ledger.get("accounts", [])
    by_code = {a["code"]: a for a in accts}
    journal = ledger.get("journal", [])
    errors = []

    # 분개장: 전표별 차대 합계와 계정별 발생액(차변 기준 부호)
    je, flow = {}, {}
    for ln in journal:
        dr, e1 = parse_amount(ln.get("debit"))
        cr, e2 = parse_amount(ln.get("credit"))
        for k, e in (("debit", e1), ("credit", e2)):
            if e:
                errors.append(("journal", ln.get("id"), f"{k}: {e}"))
        # 분개 라인은 차변·대변 중 한쪽만 적으므로 빈 쪽은 0원이다. 형식 오류는 None으로 남겨 합계를 막는다.
        dr = None if e1 else (dr or 0)
        cr = None if e2 else (cr or 0)
        kind = ln.get("kind") or "일반"
        g = je.setdefault(ln["je_no"], {"je_no": ln["je_no"], "date": ln.get("date"), "kind": kind, "lines": [], "debit": 0, "credit": 0})
        g["lines"].append(ln["id"])
        g["debit"] = _sum([g["debit"], dr])
        g["credit"] = _sum([g["credit"], cr])
        f = flow.setdefault(ln.get("code"), {"일반": 0, "수정분개": 0})
        f[kind] = _sum([f.get(kind, 0), _sub(dr, cr)])
        if ln.get("code") not in by_code:
            errors.append(("journal", ln.get("id"), f"정산표에 없는 계정 '{ln.get('code')}'"))
    for g in je.values():
        g["diff"] = _sub(g["debit"], g["credit"])

    rows = {}
    for a in accts:
        side = CATEGORY_SIDE.get(a.get("category"))
        if side is None:
            errors.append(("account", a["code"], f"알 수 없는 계정 분류 '{a.get('category')}'"))
            side = 1
        v = {}
        for col in TB_COLUMNS:
            v[col], err = parse_amount(a.get(col))
            if err:
                errors.append(("account", a["code"], f"{col}: {err}"))
        is_bs = a.get("statement") == "재무상태표"
        opening = v["prior"] if is_bs else 0
        f = flow.get(a["code"], {"일반": 0, "수정분개": 0})
        gen = None if f["일반"] is None else f["일반"] * side
        adj = None if f["수정분개"] is None else f["수정분개"] * side
        led_unadj = None if opening is None or gen is None else opening + gen
        led_adj = None if led_unadj is None or adj is None else led_unadj + adj
        rows[a["code"]] = {
            **v, "side": side, "is_bs": is_bs, "opening": opening,
            "change": _sub(v["adjusted"], v["prior"]),
            "change_rate": change_rate(_sub(v["adjusted"], v["prior"]), v["prior"]),
            "adjusted_check": _sub(v["adjusted"], _sum([v["unadjusted"], v["adjustment"]])),
            "journal_general": gen, "journal_adjustment": adj,
            "ledger_unadjusted": led_unadj, "ledger_adjusted": led_adj,
            "unadjusted_vs_journal": _sub(v["unadjusted"], led_unadj),
            "adjustment_vs_journal": _sub(v["adjustment"], adj),
        }

    # 시산표 차대 합계 (수정전·수정후). 전기말 열은 손익이 마감 전 전기 금액이라 차대 대조하지 않는다.
    tb_totals = {}
    for col in ("unadjusted", "adjusted"):
        dr = _sum(rows[c][col] for c in rows if rows[c]["side"] == 1)
        cr = _sum(rows[c][col] for c in rows if rows[c]["side"] == -1)
        tb_totals[col] = {"debit": dr, "credit": cr, "diff": _sub(dr, cr)}

    # 재무제표
    ni_line = ledger.get("net_income_line")
    lines, order = {}, []
    for a in accts:
        key = (a.get("statement"), a.get("fs_line"))
        if key not in lines:
            lines[key] = {"statement": key[0], "name": key[1], "category": a.get("category"), "accounts": []}
            order.append(key)
        lines[key]["accounts"].append(a["code"])
    rev = _sum(rows[c]["adjusted"] for c in rows if by_code[c].get("category") == "수익")
    exp = _sum(rows[c]["adjusted"] for c in rows if by_code[c].get("category") == "비용")
    rev_p = _sum(rows[c]["prior"] for c in rows if by_code[c].get("category") == "수익")
    exp_p = _sum(rows[c]["prior"] for c in rows if by_code[c].get("category") == "비용")
    ni, ni_p = _sub(rev, exp), _sub(rev_p, exp_p)
    fs_lines = []
    for key in order:
        ln = lines[key]
        cur = _sum(rows[c]["adjusted"] for c in ln["accounts"])
        pri = _sum(rows[c]["prior"] for c in ln["accounts"])
        inc_ni = ln["statement"] == "재무상태표" and ln["name"] == ni_line
        if inc_ni:
            cur = None if cur is None or ni is None else cur + ni
        tb_sums = {col: _sum(rows[c][col] for c in ln["accounts"]) for col in TB_COLUMNS + ["change"]}
        tb_sums["change_rate"] = change_rate(tb_sums["change"], tb_sums["prior"])
        fs_lines.append({**ln, "current": cur, "prior": pri, "change": _sub(cur, pri),
                         "change_rate": change_rate(_sub(cur, pri), pri), "includes_net_income": inc_ni, "tb_sums": tb_sums})

    def total(stmt, cat, col):
        return _sum(l[col] for l in fs_lines if l["statement"] == stmt and l["category"] == cat)

    bs = {}
    for col in ("current", "prior"):
        assets, liab, eq = total("재무상태표", "자산", col), total("재무상태표", "부채", col), total("재무상태표", "자본", col)
        le = _sum([liab, eq])
        bs[col] = {"자산": assets, "부채": liab, "자본": eq, "부채와자본": le, "diff": _sub(assets, le)}
    bs["change"] = {k: _sub(bs["current"][k], bs["prior"][k]) for k in ("자산", "부채", "자본", "부채와자본")}
    bs["change_rate"] = {k: change_rate(bs["change"][k], bs["prior"][k]) for k in bs["change"]}
    return {
        "accounts": rows,
        "tb_totals": tb_totals,
        "fs_lines": fs_lines,
        "bs_totals": bs,
        "income": {"revenue": rev, "expense": exp, "net_income": ni,
                   "revenue_prior": rev_p, "expense_prior": exp_p, "net_income_prior": ni_p,
                   "net_income_change": _sub(ni, ni_p), "net_income_change_rate": change_rate(_sub(ni, ni_p), ni_p)},
        "net_income_line": ni_line,
        "journal": je,
        "errors": errors,
    }


def account_ledger(ledger: dict, code: str) -> dict:
    """계정원장: 기초 잔액에서 분개 라인을 날짜·전표 순으로 쌓은 잔액(정상 잔액 방향)."""
    acct = next((a for a in ledger.get("accounts", []) if a["code"] == code), None)
    if not acct:
        raise KeyError(code)
    c = compute_ledger(ledger)["accounts"][code]
    side = c["side"]
    bal = c["opening"]
    out = []
    lines = sorted((ln for ln in ledger.get("journal", []) if ln.get("code") == code),
                   key=lambda ln: (ln.get("kind") == "수정분개", ln.get("date") or "", ln["je_no"], ln.get("line", 0)))
    for ln in lines:
        dr, _ = parse_amount(ln.get("debit"))
        cr, _ = parse_amount(ln.get("credit"))
        bal = None if bal is None else bal + ((dr or 0) - (cr or 0)) * side
        out.append({**ln, "debit": dr or 0, "credit": cr or 0, "balance": bal})
    return {"account": acct, "calc": c, "lines": out, "closing": bal, "closing_vs_adjusted": _sub(bal, c["adjusted"])}


def linked_accounts(ledger: dict | None, codes: list[str]) -> dict:
    """조서가 참조하는 정산표 계정과목의 금액과 합계."""
    if not ledger:
        return {"available": False, "rows": [], "missing": list(codes), "prior": None, "adjusted": None, "change": None}
    calc = compute_ledger(ledger)["accounts"]
    names = {a["code"]: a for a in ledger.get("accounts", [])}
    rows = [{"code": c, "name": names[c]["name"], "fs_line": names[c].get("fs_line"),
             "prior": calc[c]["prior"], "adjusted": calc[c]["adjusted"], "change": calc[c]["change"],
             "change_rate": calc[c]["change_rate"]} for c in codes if c in calc]
    prior = _sum(r["prior"] for r in rows) if rows else None
    change = _sum(r["change"] for r in rows) if rows else None
    return {"available": True, "rows": rows, "missing": [c for c in codes if c not in calc],
            "prior": prior, "adjusted": _sum(r["adjusted"] for r in rows) if rows else None,
            "change": change, "change_rate": change_rate(change, prior)}


# ---------------------------------------------------------------- 전체 계산
def compute(content: dict, data: dict, ledger: dict | None = None) -> dict:
    fields = data.get("fields", {})
    visible = {f["key"]: eval_cond(f.get("show_if"), fields) for _, f in iter_fields(content)}

    recon = data.get("recon")
    calc_sets = {st["id"]: compute_set(st, recon.get("gl_balance")) for st in recon["sets"]} if recon else {}
    active_id = recon["sets"][-1]["id"] if recon and recon["sets"] else None
    cls_calc = compute_classify(data["classify"], fields.get("as_of_date"), content.get("classify", {}).get("classes", [])) \
        if "classify" in data else None
    diffs = (diff_points(data, calc_sets) if recon else []) + classify_diffs(data, cls_calc)
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

    link = linked_accounts(ledger, data["linked_accounts"]) if "linked_accounts" in data else None
    items = run_checks(content, data, visible, calc_sets, diffs, link)
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
        "classify": cls_calc,
        "linked": link,
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
    link = str(link or "")
    if not link.startswith(("set:", "cls:")):
        return "manual"
    if any(d["key"] == link for d in diffs):
        return "open"
    if link.startswith("set:"):
        sid = link.split(":")[1]
        if not any(st["id"] == sid for st in data.get("recon", {}).get("sets", [])):
            return "missing"
    else:
        rid = link.split(":")[2]
        if not any(r["id"] == rid for r in data.get("classify", {}).get("rows", [])):
            return "missing"
    return "zero_or_blank"


def _unused_revised(data: dict) -> list[str]:
    if "recon" not in data:
        return []
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


def run_checks(content, data, visible, calc_sets, diffs, link=None) -> list[dict]:
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
        for role in required_roles(content):
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

    if "classify_blanks" in enabled:
        cls = data["classify"]
        c = compute_classify(cls, fields.get("as_of_date"), content.get("classify", {}).get("classes", []))
        if c["row_count"] == 0:
            items.append(_item("block", "미입력", "classify", "분류 검토 항목이 없음"))
        if _blank(cls.get("schedule_material_id")):
            items.append(_item("warn", "자료", "classify", "검토에 쓴 명세서 자료가 연결되지 않음"))
        for row in cls.get("rows", []):
            rc = c["rows"][row["id"]]
            name = row.get("item_id") or "(식별값 없음)"
            ref = f"crow:{row['id']}"
            if _blank(row.get("item_id")):
                items.append(_item("block", "미입력", "classify", "식별값이 없는 분류 검토 항목이 있음", ref))
            if rc["amount"] is None:
                items.append(_item("block", "미입력", "classify", f"{name}: 금액 미입력 — 분류별 합계를 계산하지 않음", ref))
            mt = row.get("maturity_type")
            if mt not in MATURITY:
                items.append(_item("block", "미입력", "classify", f"{name}: 만기 구분 미입력", ref))
            elif mt == "만기 있음":
                miss = [lab for k, lab in (("acquired_date", "취득일"), ("maturity_date", "만기일")) if _blank(row.get(k))]
                if miss:
                    items.append(_item("block", "미입력", "classify", f"{name}: {', '.join(miss)} 미입력 — 기간을 계산하지 않음", ref))
                if rc["date_order_error"]:
                    items.append(_item("block", "미입력", "classify", f"{name}: 만기일이 취득일보다 빠름", ref))
                if _blank(row.get("terms_loc")):
                    items.append(_item("warn", "미입력", "classify", f"{name}: 취득일·만기일 근거 위치 없음", ref))
            rs = row.get("restricted") or "미확인"
            if rs == "미확인":
                items.append(_item("block", "미입력", "classify", f"{name}: 사용제한 여부 미확인", ref))
            elif rs == "있음" and _blank(row.get("restriction_note")):
                items.append(_item("block", "미입력", "classify", f"{name}: 사용제한 내용 미기록", ref))
            if rs in ("없음", "있음") and _blank(row.get("restriction_loc")):
                items.append(_item("warn", "미입력", "classify", f"{name}: 사용제한 확인 근거 위치 없음", ref))
            if not rc["company"]:
                items.append(_item("block", "미입력", "classify", f"{name}: 회사 분류 미입력", ref))
            if not rc["auditor"]:
                items.append(_item("block", "미입력", "classify", f"{name}: 감사인 판단 분류 미입력", ref))
            elif _blank(row.get("basis")):
                items.append(_item("block", "미입력", "classify", f"{name}: 감사인 판단 분류의 근거 미기록", ref))
            if _blank(row.get("amount_loc")):
                items.append(_item("warn", "미입력", "classify", f"{name}: 금액 근거 위치 없음", ref))
        for k in c["unknown_classes"]:
            items.append(_item("block", "미입력", "classify", f"콘텐츠에 없는 분류 '{k}'"))
        for rid, fld, err in c["errors"]:
            items.append(_item("block", "미입력", "classify", f"형식 오류({err})", f"crow:{rid}"))

    if "ledger_link" in enabled and link is not None:
        if not link["available"]:
            items.append(_item("info", "정산표", "purpose", "이 감사건에 정산표가 없음 — 계정과목 참조 없이 작성"))
        elif not data.get("linked_accounts"):
            items.append(_item("warn", "정산표", "purpose", "이 조서가 다루는 정산표 계정과목을 선택하지 않음"))
        for c in link["missing"] if link["available"] else []:
            items.append(_item("warn", "정산표", "purpose", f"정산표에 없는 계정과목 '{c}'를 참조함"))
        if link["available"] and "recon" in data and link["adjusted"] is not None:
            gl, _ = parse_amount(data["recon"].get("gl_balance"))
            if gl is not None and gl != link["adjusted"]:
                items.append(_item("warn", "정산표", "recon",
                                   f"정산표 수정후 합계 {link['adjusted']:,}원과 입력한 총계정원장 잔액 {gl:,}원이 다름 (차이 {gl - link['adjusted']:,}원)"))

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
