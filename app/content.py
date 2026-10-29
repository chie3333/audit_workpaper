"""절차 콘텐츠 로드·검증·결합.

템플릿(공통 절차)과 계정별 설정(binding)을 합쳐 '해결된 콘텐츠'를 만든다.
조서는 만들 때의 해결된 콘텐츠를 스냅샷으로 저장하므로, 콘텐츠 파일을 고쳐도 기존 조서는 바뀌지 않는다.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from . import engine

CONTENT_DIR = Path(__file__).resolve().parent.parent / "content"
CONTENT_TYPES = {"원문 인용", "근거 요약", "보완 설명", "가상 예시"}
SOURCED_TYPES = {"원문 인용", "근거 요약"}
GUIDANCE_KINDS = {"why", "where", "how", "record", "example"}
DEFAULT_REVIEW = {"status": "AI 초안", "by": "", "date": "", "scope": ""}


class ContentError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("\n".join(errors))
        self.errors = errors


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_sources(base: Path | None = None) -> dict:
    base = base or CONTENT_DIR
    return {s["id"]: s for s in _load(base / "sources.json")["sources"]}


def load_assertions(base: Path | None = None) -> dict:
    base = base or CONTENT_DIR
    return _load(base / "assertions.json")


def list_bindings(base: Path | None = None) -> list[dict]:
    base = base or CONTENT_DIR
    out = []
    for p in sorted((base / "bindings").glob("*.json")):
        b = _load(p)
        out.append({"id": b["id"], "version": b["version"], "title": b["title"], "account": b["account"]})
    return out


def _check_refs(where: str, item: dict, sources: dict, errors: list[str]):
    refs = item.get("refs", [])
    t = item.get("type")
    if t not in CONTENT_TYPES:
        errors.append(f"{where}: 알 수 없는 내용 유형 '{t}'")
    if t in SOURCED_TYPES and not refs:
        errors.append(f"{where}: '{t}' 항목에 출처가 없음")
    for r in refs:
        if ":" not in r:
            errors.append(f"{where}: 출처 형식 오류 '{r}'")
            continue
        sid, loc = r.split(":", 1)
        if sid not in sources:
            errors.append(f"{where}: 출처 목록에 없는 자료 '{sid}'")
        elif t in SOURCED_TYPES and loc not in sources[sid]["verified_locations"]:
            errors.append(f"{where}: 근거매핑에서 확인하지 않은 위치 '{r}'")


def resolve(binding_id: str, base: Path | None = None) -> dict:
    """템플릿과 계정 설정을 합치고 검증한다. 오류가 있으면 ContentError."""
    base = base or CONTENT_DIR
    errors: list[str] = []
    sources = load_sources(base)
    assertions = load_assertions(base)
    codes = {a["code"] for a in assertions["assertions"]}
    bpath = base / "bindings" / f"{binding_id}.json"
    if not bpath.exists():
        raise ContentError([f"계정 설정 없음: {binding_id}"])
    b = _load(bpath)
    tpath = base / "templates" / f"{b['template']}.json"
    if not tpath.exists():
        raise ContentError([f"템플릿 없음: {b['template']}"])
    t = _load(tpath)
    steps = copy.deepcopy(t["steps"])
    step_ids = {s["id"] for s in steps}

    # 계정 안내를 해당 단계에 붙인다
    for g in b.get("guidance", []):
        if g.get("step") not in step_ids:
            errors.append(f"계정 안내가 없는 단계 '{g.get('step')}'를 가리킴")
            continue
        item = {k: v for k, v in g.items() if k != "step"}
        item["origin"] = "account"
        next(s for s in steps if s["id"] == g["step"])["guidance"].append(item)

    field_keys: set[str] = set()
    for s in steps:
        for i, g in enumerate(s["guidance"]):
            where = f"[{s['id']}] 안내 {i + 1}"
            if g.get("kind") not in GUIDANCE_KINDS:
                errors.append(f"{where}: 알 수 없는 안내 구분 '{g.get('kind')}'")
            _check_refs(where, g, sources, errors)
            g.setdefault("unverified", False)
            g.setdefault("origin", "template")
            g.setdefault("review", dict(DEFAULT_REVIEW))
        for comp in s["components"]:
            if comp["type"] not in engine.COMPONENTS:
                errors.append(f"[{s['id']}] 지원하지 않는 구성요소 '{comp['type']}'")
            for f in comp.get("fields", []):
                if f["type"] not in engine.FIELD_TYPES:
                    errors.append(f"[{s['id']}] 필드 '{f['key']}': 지원하지 않는 입력 유형 '{f['type']}'")
                if f["key"] in field_keys:
                    errors.append(f"필드 키 중복 '{f['key']}'")
                field_keys.add(f["key"])
                if f["type"] == "choice" and not f.get("options"):
                    errors.append(f"필드 '{f['key']}': 선택지 없음")
        for c in s.get("calcs", []):
            if c not in engine.CALCS:
                errors.append(f"[{s['id']}] 지원하지 않는 계산 규칙 '{c}'")
    for s in steps:
        for comp in s["components"]:
            for f in comp.get("fields", []):
                cond = f.get("show_if")
                if cond and cond.get("field") not in field_keys:
                    errors.append(f"필드 '{f['key']}'의 표시 조건이 없는 필드 '{cond.get('field')}'를 참조")
    for c in t.get("checks", []):
        if c not in engine.CHECKS:
            errors.append(f"지원하지 않는 점검 규칙 '{c}'")

    a = copy.deepcopy(b["assertions"])
    for code in a["default"]:
        if code not in codes:
            errors.append(f"알 수 없는 경영진 주장 코드 '{code}'")
    _check_refs("경영진 주장", a, sources, errors)
    a.setdefault("review", dict(DEFAULT_REVIEW))
    required = t.get("required_documents", engine.REQUIRED_ROLES)
    for role in required:
        if role not in b.get("documents", {}):
            errors.append(f"자료명 없음: {role}")
    comps = {comp["type"] for s in steps for comp in s["components"]}
    if "classify" in comps and not b.get("classify", {}).get("classes"):
        errors.append("분류 검토 절차에 분류 선택지(classify.classes)가 없음")
    if errors:
        raise ContentError(errors)

    resolved = {
        "id": b["id"],
        "version": b["version"],
        "template": {"id": t["id"], "version": t["version"], "title": t["title"]},
        "title": b["title"],
        "account": b["account"],
        "form_ref": b.get("form_ref"),
        "assertions": a,
        "assertion_list": assertions["assertions"],
        "documents": dict(b["documents"], other="기타 자료"),
        "row": b["row"],
        "steps": steps,
        "checks": t.get("checks", []),
        "export": t.get("export", {}),
        "sources": {sid: {k: v for k, v in s.items() if k != "verified_locations"} | {"locations": s["verified_locations"]}
                    for sid, s in sources.items()},
    }
    # 기존 콘텐츠의 해시가 바뀌지 않도록, 새 키는 정의된 경우에만 넣는다
    if "required_documents" in t:
        resolved["required_documents"] = list(required)
    if "classify" in b:
        resolved["classify"] = copy.deepcopy(b["classify"])
    if "ledger_fs_lines" in b:
        resolved["ledger_fs_lines"] = list(b["ledger_fs_lines"])
    resolved["content_key"] = f"{b['id']}@{b['version']}+{t['id']}@{t['version']}"
    resolved["hash"] = content_hash(resolved)
    return resolved


def content_hash(resolved: dict) -> str:
    body = {k: v for k, v in resolved.items() if k != "hash"}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def validate_all(base: Path | None = None) -> dict:
    base = base or CONTENT_DIR
    report = {}
    for b in list_bindings(base):
        try:
            r = resolve(b["id"], base)
            report[b["id"]] = {"ok": True, "content_key": r["content_key"], "errors": []}
        except ContentError as e:
            report[b["id"]] = {"ok": False, "errors": e.errors}
    return report
