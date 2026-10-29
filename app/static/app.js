/* 실증절차 조서 작성 화면.
   화면은 콘텐츠(서버가 준 절차 정의)를 읽어 그린다. 계산·표시 조건·남은 작업은 서버 preview 결과만 쓴다. */
"use strict";

// ------------------------------------------------------------------ 공통
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "text") el.textContent = v;
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

async function api(method, url, body) {
  const res = await fetch(url, {
    method, headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let msg = `${res.status}`;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : (j.detail?.errors || [j.detail?.message]).join("\n");
    } catch (_) { /* 본문 없음 */ }
    const err = new Error(msg); err.status = res.status; throw err;
  }
  return res.json();
}

function put(el, ...kids) { el.replaceChildren(...kids.flat().filter((k) => k !== null && k !== undefined && k !== false)); return el; }
const fmt = (n) => (n === null || n === undefined ? "미입력" : Number(n).toLocaleString("ko-KR"));
const newId = (p) => p + Math.random().toString(36).slice(2, 10);
const blank = (v) => v === null || v === undefined || String(v).trim() === "";

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), 2600);
}

function modal(title, body, buttons) {
  const m = $("#modal");
  $("#modal-title").textContent = title;
  const b = $("#modal-body"); put(b, ...[].concat(body));
  const a = $("#modal-actions"); put(a);
  return new Promise((resolve) => {
    for (const [label, value, cls] of buttons) {
      a.append(h("button", { class: "btn " + (cls || ""), type: "button", onclick: () => { m.hidden = true; resolve(value); } }, label));
    }
    m.hidden = false;
    (b.querySelector("input,textarea,select") || a.lastChild)?.focus();
  });
}
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("#modal").hidden) $("#modal-actions button")?.click();
  if ((e.ctrlKey || e.metaKey) && e.key === "s" && S.wp) { e.preventDefault(); saveDialog(); }
});

// ------------------------------------------------------------------ 상태
const S = { wp: null, data: null, computed: null, dirty: false, step: "purpose", setTab: null, readOnly: false, seq: 0, timer: null };
const LABEL = { schedule: "명세서", subledger: "보조부", gl: "총계정원장", terms: "증서·약정서", restriction: "사용제한 자료", other: "기타" };
const KINDS = [["why", "왜 하는가"], ["where", "어디를 보는가"], ["how", "어떻게 확인하는가"], ["record", "조서에 어떻게 기록하는가"], ["example", "작성 예시 (참고용)"]];

window.addEventListener("beforeunload", (e) => { if (S.dirty) { e.preventDefault(); e.returnValue = ""; } });
let lastHash = location.hash;
window.addEventListener("hashchange", async () => {
  if (S.dirty) {
    const target = location.hash;
    history.replaceState(null, "", lastHash || "#");
    const ok = await modal("저장하지 않은 변경 사항", [h("p", {}, "저장하지 않은 입력이 있습니다. 이동하면 사라집니다.")],
      [["취소", false], ["버리고 이동", true, "primary"]]);
    if (!ok) return;
    S.dirty = false; history.replaceState(null, "", target);
  }
  lastHash = location.hash;
  route();
});
route();

function route() {
  const m = location.hash.match(/^#wp-(\d+)(?:-r(\d+))?$/);
  const l = location.hash.match(/^#eng-(\d+)(?:-(tb|acct|je)(?:-(.+))?)?$/);
  if (m) openWp(+m[1], m[2] ? +m[2] : null).catch(showError);
  else if (l) ledgerView(+l[1], l[2] || "fs", l[3] ? decodeURIComponent(l[3]) : null).catch(showError);
  else home().catch(showError);
}

function showError(e) {
  put($("#app"), h("div", { class: "paper step" }, h("h1", {}, "불러오지 못함"), h("p", { class: "err" }, e.message)));
}

// ------------------------------------------------------------------ 경로로 값 읽기·쓰기 ("materials.#m1.name")
function resolveSeg(obj, seg) {
  if (seg.startsWith("#")) return obj.find((x) => x.id === seg.slice(1));
  return obj[seg];
}
function getPath(path) {
  let o = S.data;
  for (const seg of path.split(".")) { if (o == null) return undefined; o = resolveSeg(o, seg); }
  return o;
}
function setPath(path, value) {
  const segs = path.split(".");
  let o = S.data;
  for (const seg of segs.slice(0, -1)) o = resolveSeg(o, seg);
  o[segs[segs.length - 1]] = value;
}

function markDirty() {
  if (S.readOnly) return;
  S.dirty = true;
  renderTop();
  clearTimeout(S.timer);
  S.timer = setTimeout(preview, 250);
}

async function preview() {
  const seq = ++S.seq;
  try {
    const c = await api("POST", `/api/workpapers/${S.wp.id}/preview`, { data: S.data });
    if (seq !== S.seq) return;
    S.computed = c; applyComputed();
  } catch (e) { toast("계산 갱신 실패: " + e.message); }
}

function mutate(fn) {
  fn(S.data);
  markDirty();
  renderStep();
}

// ------------------------------------------------------------------ 입력 요소
function input(path, type = "text", opts = {}) {
  const v = getPath(path);
  let el;
  if (type === "textarea") el = h("textarea", { id: opts.id, rows: opts.rows || 3 });
  else if (type === "choice") {
    el = h("select", { id: opts.id }, h("option", { value: "" }, "선택"), ...(opts.options || []).map((o) =>
      Array.isArray(o) ? h("option", { value: o[0] }, o[1]) : h("option", { value: o }, o)));
  } else if (type === "checkbox") el = h("input", { type: "checkbox", id: opts.id });
  else el = h("input", { type: type === "date" ? "date" : "text", id: opts.id, class: type === "amount" ? "amount" : null,
    inputmode: type === "amount" ? "numeric" : null, placeholder: type === "amount" ? "미입력" : (opts.placeholder || null) });
  if (type === "checkbox") el.checked = !!v; else el.value = v ?? "";
  if (type === "amount") el.value = formatAmountText(v);
  el.dataset.path = path;
  el.addEventListener(type === "checkbox" || type === "choice" ? "change" : "input", () => {
    let val = type === "checkbox" ? el.checked : el.value;
    if (type === "amount") { val = val.replace(/,/g, "").trim(); el.classList.toggle("invalid", val !== "" && !/^-?\d+$/.test(val)); }
    setPath(path, val);
    markDirty();
    if (opts.rerender) renderStep();
  });
  if (type === "amount") el.addEventListener("blur", () => { el.value = formatAmountText(getPath(path)); });
  return el;
}
function formatAmountText(v) {
  if (blank(v)) return "";
  const s = String(v).replace(/,/g, "").trim();
  return /^-?\d+$/.test(s) ? Number(s).toLocaleString("ko-KR") : String(v);
}

function fieldBox(label, el, { req, help, wide, vis, ui, ref } = {}) {
  if (el.id === undefined || el.id === "") el.id = newId("f");
  return h("div", { class: "field" + (wide ? " wide" : ""), dataset: { vis: vis || "", ui: ui || "", ref: ref || "" } },
    h("label", { for: el.id }, label, req ? h("span", { class: "req", title: "필수" }, "*") : null),
    el, help ? h("div", { class: "help" }, help) : null);
}

// ------------------------------------------------------------------ 홈
async function home() {
  S.wp = null; S.dirty = false; renderTop();
  const [tree, procs] = await Promise.all([api("GET", "/api/tree"), api("GET", "/api/procedures")]);
  const list = h("section", { class: "paper" }, h("h1", {}, "조서"),
    h("p", { class: "intro" }, "회사·보고기간별로 조서가 따로 저장됩니다. 조서를 열면 단계별 안내를 보면서 입력하고, 저장한 뒤 엑셀로 내려받을 수 있습니다."));
  if (!tree.length) list.append(h("p", { class: "sub" }, "아직 조서가 없습니다. 오른쪽에서 새 조서를 만드세요. 가상 사례는 scripts/seed_samples.py로 넣을 수 있습니다."));
  for (const c of tree) {
    const co = h("div", { class: "co" }, h("h3", {}, c.name, c.is_sample ? h("span", { class: "chip sample" }, "가상 데이터") : null));
    for (const e of c.engagements) {
      const eng = h("div", { class: "eng" }, h("div", { class: "sub" }, `보고기간 종료일 ${e.period_end} · ${e.currency} · ${e.unit}`,
        e.has_ledger ? h("a", { class: "btn small", href: `#eng-${e.id}`, style: "margin-left:8px" }, "재무제표 → 정산표 → 원장 → 분개장") : null));
      for (const w of e.workpapers) {
        eng.append(h("div", { class: "wpl" },
          h("a", { href: `#wp-${w.id}` }, w.title),
          h("span", { class: "sub" }, `리비전 ${w.rev} · ${w.saved_at?.replace("T", " ")}${w.locked ? " · 잠김" : ""}`)));
      }
      if (!e.workpapers.length) eng.append(h("div", { class: "sub" }, "조서 없음"));
      co.append(eng);
    }
    list.append(co);
  }
  const coSel = h("select", { id: "new-co" }, h("option", { value: "" }, "새 회사 입력"), ...tree.map((c) => h("option", { value: c.id }, c.name)));
  const coName = h("input", { type: "text", id: "new-co-name", placeholder: "회사명" });
  const period = h("input", { type: "date", id: "new-period" });
  const proc = h("select", { id: "new-proc" }, ...procs.map((p) => h("option", { value: p.id }, `${p.title} (v${p.version})`)));
  const err = h("div", { class: "err" });
  coSel.addEventListener("change", () => { coName.parentElement.hidden = !!coSel.value; });
  const form = h("section", { class: "paper" }, h("h1", {}, "새 조서"),
    fieldBox("회사", coSel), fieldBox("새 회사명", coName), fieldBox("보고기간 종료일", period, { req: true }),
    fieldBox("실증절차", proc, { req: true }), err,
    h("div", {}, h("button", { class: "btn primary", type: "button", onclick: async () => {
      err.textContent = "";
      try {
        let cid = coSel.value;
        if (!cid) cid = (await api("POST", "/api/companies", { name: coName.value })).id;
        const company = tree.find((c) => String(c.id) === String(cid));
        let eid = company?.engagements.find((e) => e.period_end === period.value)?.id;
        if (!eid) eid = (await api("POST", "/api/engagements", { company_id: +cid, period_end: period.value })).id;
        const { id } = await api("POST", "/api/workpapers", { engagement_id: eid, procedure_id: proc.value });
        location.hash = `#wp-${id}`;
      } catch (e) { err.textContent = e.message; }
    } }, "조서 만들기")));
  put($("#app"), h("div", { class: "home" }, list, form));
}

// ------------------------------------------------------------------ 조서 열기
async function openWp(id, rev) {
  const wp = await api("GET", `/api/workpapers/${id}${rev ? `?rev=${rev}` : ""}`);
  load(wp);
  S.readOnly = !!rev && rev !== wp.latest_rev;
  if (!wp.content.steps.some((s) => s.id === S.step)) S.step = wp.content.steps[0].id;
  renderEditor();
}
function load(wp) {
  S.wp = wp; S.data = wp.data; S.computed = wp.computed; S.dirty = false; S.setTab = null;
}

function renderEditor() {
  put($("#app"), h("div", { class: "editor" },
    h("nav", { class: "side", "aria-label": "단계" }, h("ol", { id: "nav" })),
    h("section", { class: "paper step", id: "step" }),
    h("aside", { class: "paper todo", id: "todo", "aria-label": "남은 작업" })));
  renderNav(); renderStep(); renderTodo(); renderTop();
}

function renderTop() {
  const crumb = $("#crumb"), chips = $("#chips"), actions = $("#actions");
  if (!S.wp) { put(crumb); put(chips); put(actions); return; }
  const f = S.data.fields, st = S.computed.status;
  put(crumb, h("b", {}, S.wp.company), ` · 대상일 ${f.as_of_date || S.wp.period_end} · ${S.wp.content.title}`);
  const proc = h("span", { class: "chip " + (st.procedure === "수행 완료" ? (st.procedure_ready ? "ok" : "warn") : "") },
    h("i", {}, "수행"), st.procedure, st.blocking_count ? ` · 남은 작업 ${st.blocking_count}` : "");
  const fnd = h("span", { class: "chip " + (st.findings_unresolved ? "mark" : "ok") }, h("i", {}, "발견 사항"), st.findings);
  const rv = h("span", { class: "chip " + (st.review === "검토 완료" ? "ok" : "warn") }, h("i", {}, "검토"), st.review);
  put(chips, 
    S.wp.is_sample ? h("span", { class: "chip sample" }, "가상 데이터") : null,
    S.wp.locked ? h("span", { class: "chip warn", title: "업무용 잠금. 최종 감사파일 취합·법정 보존 기능이 아닙니다." }, "편집 잠금") : null,
    S.readOnly ? h("span", { class: "chip warn" }, `리비전 ${S.wp.rev} 보기`) : null, proc, fnd, rv);
  put(actions, 
    h("span", { class: "sub" }, `리비전 ${S.wp.rev}`), S.dirty ? h("span", { class: "dirty-dot" }, "● 저장 안 됨") : null,
    S.readOnly ? h("a", { class: "btn", href: `#wp-${S.wp.id}` }, "최신 저장본으로") :
      h("button", { class: "btn primary", type: "button", onclick: saveDialog }, "저장"),
    h("button", { class: "btn", type: "button", onclick: exportDialog }, "엑셀"),
    h("button", { class: "btn", type: "button", onclick: historyDialog }, "이력"),
    S.readOnly ? null : h("button", { class: "btn", type: "button", onclick: lockDialog }, S.wp.locked ? "잠금 해제" : "잠금"));
}

function renderNav() {
  const nav = $("#nav"); if (!nav) return;
  put(nav, ...S.wp.content.steps.map((s, i) => {
    const c = S.computed.step_counts[s.id] || { block: 0, warn: 0 };
    return h("li", {}, h("button", { type: "button", "aria-current": s.id === S.step ? "step" : null, onclick: () => { S.step = s.id; renderNav(); renderStep(); window.scrollTo({ top: 0 }); } },
      h("span", {}, h("span", { class: "n" }, i + 1), s.title),
      h("span", { class: "count" + (c.block ? "" : " zero"), title: `남은 작업 ${c.block}, 주의 ${c.warn}` }, c.block ? c.block : "✓")));
  }));
}

function renderTodo() {
  const box = $("#todo"); if (!box) return;
  const items = S.computed.open_items;
  const titles = Object.fromEntries(S.wp.content.steps.map((s) => [s.id, s.title]));
  const order = { block: 0, warn: 1, info: 2 };
  const nb = items.filter((i) => i.level === "block").length;
  put(box, 
    h("h2", {}, "남은 작업", h("span", { class: "sub" }, `${nb}건 · 주의 ${items.length - nb}건`)),
    h("p", { class: "sub", style: "margin:0" }, "입력이 비었거나 확인이 끝나지 않은 항목입니다. 결론과 엑셀에도 그대로 표시됩니다. 판단이 맞는지는 알려주지 않습니다."),
    items.length ? h("ul", {}, ...[...items].sort((a, b) => order[a.level] - order[b.level]).map((it) =>
      h("li", {}, h("button", { type: "button", class: "item " + it.level, onclick: () => goTo(it) },
        h("span", {}, it.message, h("small", {}, `${titles[it.step] || it.step} · ${it.category}`)))))) :
      h("p", {}, "남은 작업 없음"));
}

function goTo(it) {
  S.step = it.step; renderNav(); renderStep();
  requestAnimationFrame(() => {
    let el = it.ref && $(`[data-ref="${CSS.escape(it.ref)}"]`);
    if (!el && (it.ref?.startsWith("set:") || it.ref?.startsWith("cls:"))) { S.step = "findings"; renderNav(); renderStep(); el = $(`[data-ref="${CSS.escape(it.ref)}"]`); }
    el = el || $("#step");
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash");
  });
}

// ------------------------------------------------------------------ 단계 그리기
function renderStep() {
  const box = $("#step"); if (!box) return;
  const step = S.wp.content.steps.find((s) => s.id === S.step);
  put(box, 
    h("h1", {}, step.title),
    S.readOnly ? h("div", { class: "readonly-note" }, `이전 저장본(리비전 ${S.wp.rev})을 보고 있습니다. 수정할 수 없습니다.`) : null,
    S.wp.locked && !S.readOnly ? h("div", { class: "readonly-note" }, "편집 잠금 상태입니다. 저장하려면 수정 이유를 적어야 합니다. 이 잠금은 업무용이며 최종 감사파일 취합·법정 보존 기능이 아닙니다.") : null,
    guide(step),
    ...step.components.map((c) => COMPONENTS[c.type] ? COMPONENTS[c.type](c, step) :
      h("p", { class: "err" }, `이 화면이 모르는 구성요소 '${c.type}' — 새로고침(Cmd+Shift+R)해 보세요.`)));
  if (S.readOnly) $$("input,select,textarea,button:not(.keep)", box).forEach((el) => (el.disabled = true));
  applyComputed();
}

function guide(step) {
  const src = S.wp.content.sources;
  const dl = h("dl");
  for (const [kind, label] of KINDS) {
    const items = step.guidance.filter((g) => g.kind === kind);
    if (!items.length) continue;
    dl.append(h("dt", {}, label), h("dd", {}, ...items.map((g) => h("div", { class: "gitem" },
      h("p", {}, g.text),
      h("div", { class: "tags" },
        h("span", { class: "tag" + (g.type === "가상 예시" ? " ex" : "") }, g.type),
        ...(g.refs || []).map((r) => {
          const [sid, loc] = r.split(":");
          const s = src[sid];
          const title = s ? `${s.title} ${s.edition}\n${loc}: ${s.locations[loc] || "근거매핑에 없는 위치"}` : r;
          return h("span", { class: "tag src", title }, sid === "KSA2026" ? `감사기준서 ${loc}` : `서식 ${loc}`);
        }),
        g.unverified ? h("span", { class: "tag unv" }, "미확인") : null,
        h("span", { class: "tag " + (g.review?.status === "사용자 검토 완료" ? "done" : "draft") }, g.review?.status || "AI 초안"),
        g.origin === "account" ? h("span", { class: "tag" }, "계정별 안내") : null)))));
  }
  return h("details", { class: "guide", open: true }, h("summary", {}, "안내"), dl,
    h("p", { class: "sub" }, `콘텐츠 ${S.wp.content.content_key}. 'AI 초안'은 실무 검토 전 문구입니다. 예시 문장은 참고용이며 조서에 자동으로 들어가지 않습니다.`));
}

// ------------------------------------------------------------------ 구성요소
const COMPONENTS = {
  fields(comp) {
    return h("div", { class: "fields" }, ...comp.fields.map((f) => fieldBox(f.label,
      input(`fields.${f.key}`, f.type, { options: f.options, rows: 3 }),
      { req: f.required, help: f.help, wide: f.type === "textarea", vis: f.key, ref: `field:${f.key}` })));
  },

  accounts() {
    const led = S.wp.ledger;
    const box = h("div", { class: "block" }, h("div", { class: "block-head" }, h("h2", {}, "정산표 계정과목"),
      led ? h("a", { class: "btn small", href: `#eng-${S.wp.engagement_id}` }, "재무제표부터 보기") : null));
    if (!led) return put(box, box.firstChild, h("p", { class: "sub", style: "margin:0" }, "이 감사건에 정산표가 없습니다. 계정과목 참조 없이 작성합니다."));
    box.append(h("p", { class: "sub", style: "margin:0" }, "이 조서가 다루는 계정과목을 고르세요. 정산표 금액은 참조로만 보여주며 조서 입력값을 대신하지 않습니다."));
    const cur = new Set(S.data.linked_accounts);
    const hint = new Set(S.wp.content.ledger_fs_lines || []);
    const pick = (a) => {
      const cb = h("input", { type: "checkbox", value: a.code });
      cb.checked = cur.has(a.code);
      cb.addEventListener("change", () => mutate((d) => {
        const set = new Set(d.linked_accounts); cb.checked ? set.add(a.code) : set.delete(a.code);
        d.linked_accounts = led.accounts.map((x) => x.code).filter((c) => set.has(c));
      }));
      return h("label", { class: cur.has(a.code) ? "on" : "" }, cb, `${a.code} ${a.name}`, h("small", {}, a.fs_line));
    };
    const main = led.accounts.filter((a) => hint.has(a.fs_line)), rest = led.accounts.filter((a) => !hint.has(a.fs_line));
    box.append(h("div", { class: "assertions", role: "group", "aria-label": "이 절차 대상 계정과목" }, ...main.map(pick)));
    if (rest.length) box.append(h("details", {}, h("summary", { class: "sub" }, `다른 계정과목 ${rest.length}개`),
      h("div", { class: "assertions", style: "margin-top:6px" }, ...rest.map(pick))));
    box.append(h("div", { id: "linked-accounts" }));
    return box;
  },

  assertions() {
    const a = S.wp.content.assertions, cur = new Set(S.data.assertions.applied);
    const chips = h("div", { class: "assertions", role: "group", "aria-label": "적용 경영진 주장" },
      ...S.wp.content.assertion_list.map((x) => {
        const cb = h("input", { type: "checkbox", value: x.code });
        cb.checked = cur.has(x.code);
        cb.addEventListener("change", () => mutate((d) => {
          const s = new Set(d.assertions.applied); cb.checked ? s.add(x.code) : s.delete(x.code);
          d.assertions.applied = S.wp.content.assertion_list.map((y) => y.code).filter((c) => s.has(c));
        }));
        return h("label", { class: cur.has(x.code) ? "on" : "" }, cb, `${x.name} (${x.code})`, a.default.includes(x.code) ? h("small", {}, "기본") : null);
      }));
    return h("div", { class: "block" },
      h("div", { class: "block-head" }, h("h2", {}, "적용 경영진 주장"),
        h("div", { class: "tags" }, h("span", { class: "tag" }, a.type), ...a.refs.map((r) => h("span", { class: "tag src" }, "서식 " + r.split(":")[1])),
          a.unverified ? h("span", { class: "tag unv" }, "미확인") : null,
          h("span", { class: "tag " + (a.review?.status === "사용자 검토 완료" ? "done" : "draft") }, a.review?.status))),
      chips, h("p", { class: "sub", style: "margin:0" }, a.note),
      h("div", { dataset: { ui: "assertion_changed" } },
        fieldBox("기본값과 다르게 적용한 이유", input("assertions.change_reason", "textarea"), { req: true, wide: true })));
  },

  materials() {
    const box = h("div", { class: "block" },
      h("div", { class: "block-head" }, h("h2", {}, "자료 목록"),
        h("div", { class: "chips" }, ...Object.keys(S.wp.content.documents).map((role) =>
          h("button", { class: "btn small", type: "button", onclick: () => mutate((d) => d.materials.push({
            id: newId("m"), role, name: "", version_label: "", kind: "원본", original_id: "", provider: "", receipt: "요청",
            requested_date: "", received_date: "", as_of_date: S.data.fields.as_of_date || "", location: "", remaining_work: "",
            confirmed: false, confirmed_by: "", confirmed_date: "", confirmed_scope: "", note: "" })) }, "+ " + LABEL[role])))),
      h("p", { class: "sub", style: "margin:0" }, "자료를 '입수'로 등록한 것과 증거로 확인한 것은 다릅니다. 확인했다면 확인자·확인일·확인 범위를 남기세요. 파일은 이 도구에 올리지 않고 위치만 적습니다."));
    const cards = h("div", { class: "cards" });
    const docs = Object.entries(S.wp.content.documents).filter(([k]) => k !== "other").map(([, v]) => v);
    if (!S.data.materials.length) cards.append(h("p", { class: "sub" }, `등록된 자료가 없습니다. ${docs.join(", ")}을 등록하세요.`));
    for (const m of S.data.materials) {
      const p = `materials.#${m.id}`;
      const same = S.data.materials.filter((x) => x.role === m.role && x.id !== m.id);
      cards.append(h("div", { class: "card" + (m.receipt !== "입수" ? " attn" : ""), dataset: { ref: `material:${m.id}` } },
        h("div", { class: "card-head" },
          h("b", {}, `${LABEL[m.role]} · ${m.name || "(이름 없음)"}`),
          h("div", { class: "chips" },
            h("span", { class: "chip " + (m.kind === "수정본" ? "warn" : "") }, m.kind || "원본"),
            h("span", { class: "chip " + (m.receipt === "입수" ? "ok" : "mark") }, m.receipt || "상태 미입력"),
            m.receipt === "입수" ? h("span", { class: "chip " + (m.confirmed ? "ok" : "warn") }, m.confirmed ? "증거 확인함" : "등록만 됨") : null,
            h("button", { class: "btn link", type: "button", onclick: () => removeMaterial(m.id) }, "삭제"))),
        h("div", { class: "fields" },
          fieldBox("자료명", input(`${p}.name`), { req: true }),
          fieldBox("버전·식별", input(`${p}.version_label`)),
          fieldBox("원본/수정본", input(`${p}.kind`, "choice", { options: ["원본", "수정본"], rerender: true })),
          fieldBox("원본 자료", input(`${p}.original_id`, "choice", { options: same.map((x) => [x.id, x.name || "(이름 없음)"]) }),
            { req: true, ui: `materials.${m.id}.show_original` }),
          fieldBox("제공자", input(`${p}.provider`)),
          fieldBox("입수 상태", input(`${p}.receipt`, "choice", { options: ["요청 전", "요청", "입수", "입수 불가"], rerender: true })),
          fieldBox("요청일", input(`${p}.requested_date`, "date")),
          fieldBox("입수일", input(`${p}.received_date`, "date")),
          fieldBox("자료 기준일", input(`${p}.as_of_date`, "date")),
          fieldBox("위치 (파일명·시트·페이지 등)", input(`${p}.location`), { wide: true }),
          fieldBox("남은 작업", input(`${p}.remaining_work`, "textarea"), { wide: true, req: true, ui: `materials.${m.id}.show_remaining`,
            help: "무엇을 언제 요청했고, 받으면 무엇을 할지" }),
          h("div", { class: "field wide", dataset: { ui: `materials.${m.id}.show_confirm` } },
            h("label", { class: "check" }, input(`${p}.confirmed`, "checkbox", { rerender: true }), "이 자료를 증거로 확인함"),
            m.confirmed ? h("div", { class: "fields" },
              fieldBox("확인자", input(`${p}.confirmed_by`), { req: true }),
              fieldBox("확인일", input(`${p}.confirmed_date`, "date"), { req: true }),
              fieldBox("확인 범위", input(`${p}.confirmed_scope`), { req: true, help: "예: 계좌 목록, 행별 금액, 표시 합계" })) : null),
          fieldBox("비고", input(`${p}.note`), { wide: true }))));
    }
    box.append(cards);
    return box;
  },

  recon() {
    const sets = S.data.recon.sets, last = sets[sets.length - 1];
    if (!S.setTab || !sets.some((s) => s.id === S.setTab)) S.setTab = last.id;
    const st = sets.find((s) => s.id === S.setTab);
    const editable = st.id === last.id;
    const schedMats = S.data.materials.filter((m) => m.role === "schedule");
    const sp = `recon.sets.#${st.id}`;
    const extra = S.wp.content.row.extra_columns || [];
    const box = h("div", { class: "block" });
    box.append(h("div", { class: "block-head" }, h("h2", {}, "검토표"),
      sets.length > 1 ? h("div", { class: "settabs" }, ...sets.map((s) => h("button", { type: "button", class: "keep", "aria-pressed": s.id === st.id ? "true" : "false",
        onclick: () => { S.setTab = s.id; renderStep(); } }, s.label + (s.id === last.id ? " (현재)" : " (보존)")))) : null));
    if (!editable) box.append(h("div", { class: "readonly-note" }, "수정 전 대사 기록입니다. 원본 보존을 위해 수정할 수 없습니다."));
    box.append(h("div", { class: "fields" },
      fieldBox("대사에 쓴 명세서 자료", input(`${sp}.schedule_material_id`, "choice", { options: schedMats.map((m) => [m.id, `${m.name} ${m.version_label || ""} (${m.kind})`]) })),
      fieldBox("명세서 표시 합계", input(`${sp}.stated_total`, "amount"), { req: true }),
      fieldBox("표시 합계 위치", input(`${sp}.stated_total_loc`))));

    const head = ["#", S.wp.content.row.id_label, S.wp.content.row.name_label, ...extra.map((x) => x.label),
      "명세서 금액", "보조부 금액", "차이 (명세서−보조부)", "명세서 근거 위치", "보조부 근거 위치", "비고", "비경상", ""];
    const tbody = h("tbody");
    st.rows.forEach((r, i) => {
      const rp = `${sp}.rows.#${r.id}`;
      tbody.append(h("tr", { dataset: { ref: `row:${r.id}` } },
        h("td", { class: "num" }, i + 1),
        h("td", {}, input(`${rp}.item_id`, "text", { placeholder: "예: K01" })),
        h("td", {}, input(`${rp}.name`)),
        ...extra.map((x) => h("td", {}, input(`${rp}.${x.key}`, x.type, { options: x.options }))),
        h("td", {}, input(`${rp}.schedule_amount`, "amount")),
        h("td", {}, input(`${rp}.subledger_amount`, "amount")),
        h("td", { class: "num diffcell", dataset: { calc: `row:${st.id}:${r.id}` } }),
        h("td", {}, input(`${rp}.schedule_loc`)),
        h("td", {}, input(`${rp}.subledger_loc`)),
        h("td", {}, input(`${rp}.note`)),
        h("td", {}, h("label", { class: "check" }, input(`${rp}.unusual`, "checkbox", { rerender: true }), "표시"),
          r.unusual ? input(`${rp}.unusual_reason`, "text", { placeholder: "이유" }) : null),
        h("td", {}, editable ? h("button", { class: "btn link", type: "button", onclick: () => mutate(() => { st.rows = st.rows.filter((x) => x.id !== r.id); }) }, "삭제") : null)));
    });
    if (!st.rows.length) tbody.append(h("tr", {}, h("td", { colspan: head.length, class: "sub" }, "대사 항목이 없습니다. 아래에서 추가하세요.")));
    const cols = h("colgroup", {}, h("col", { class: "c-n" }), h("col", { class: "c-id" }), h("col", { class: "c-name" }),
      ...extra.map(() => h("col", { class: "c-x" })), h("col", { class: "c-amt" }), h("col", { class: "c-amt" }), h("col", { class: "c-diff" }),
      h("col", { class: "c-loc" }), h("col", { class: "c-loc" }), h("col", { class: "c-note" }), h("col", { class: "c-un" }), h("col", { class: "c-del" }));
    const table = h("div", { class: "tablewrap" }, h("table", { class: "recon" }, cols, h("thead", {}, h("tr", {}, ...head.map((x) => h("th", {}, x)))), tbody));
    box.append(table);
    if (editable) box.append(h("div", {}, h("button", { class: "btn small", type: "button", onclick: () => mutate(() => st.rows.push({
      id: newId("r"), item_id: "", name: "", product_type: "", schedule_amount: "", subledger_amount: "", schedule_loc: "", subledger_loc: "",
      note: "", unusual: false, unusual_reason: "" })) }, "+ 대사 항목 추가")));
    if (!editable) $$("input,select,textarea", table).forEach((el) => (el.disabled = true));
    if (!editable) $$("input,select", box.querySelector(".fields")).forEach((el) => (el.disabled = true));

    const glMats = S.data.materials.filter((m) => m.role === "gl");
    box.append(h("h2", {}, "합계와 장부 연결"),
      h("div", { class: "totals" },
        tot("명세서 재계산 합계", `tot:${st.id}:recalc_total`),
        tot("표시 합계 − 재계산 합계", `tot:${st.id}:stated_vs_recalc`, true),
        tot("보조부 합계", `tot:${st.id}:subledger_total`),
        tot("보조부 합계 − 총계정원장 잔액", `tot:${st.id}:subledger_vs_gl`, true)),
      h("div", { class: "fields" },
        fieldBox("총계정원장 잔액", input("recon.gl_balance", "amount"), { req: true, help: "모든 대사 기록이 같은 잔액을 씁니다." }),
        fieldBox("총계정원장 근거 위치", input("recon.gl_loc")),
        fieldBox("총계정원장 자료", input("recon.gl_material_id", "choice", { options: glMats.map((m) => [m.id, m.name]) }))),
      h("div", { dataset: { region: "revised" } }));
    return box;
  },

  classify() {
    const cls = S.data.classify, row = S.wp.content.row, classes = S.wp.content.classify.classes;
    const extra = row.extra_columns || [];
    const schedMats = S.data.materials.filter((m) => m.role === "schedule");
    const box = h("div", { class: "block" }, h("h2", {}, "분류 검토표"),
      h("p", { class: "sub", style: "margin:0" }, "일수는 프로그램이 계산합니다. 몇 개월 이내인지, 어느 분류가 맞는지는 판단하지 않습니다. 감사인 판단 분류와 근거는 직접 적으세요."),
      h("div", { class: "fields" },
        fieldBox("검토에 쓴 명세서 자료", input("classify.schedule_material_id", "choice", { options: schedMats.map((m) => [m.id, `${m.name} ${m.version_label || ""} (${m.kind})`]) }))));
    const head = ["#", row.id_label, row.name_label, ...extra.map((x) => x.label), "금액", "금액 근거 위치", "만기 구분", "취득일", "만기일",
      "취득→만기 (일)", "대상일→만기 (일)", "날짜 근거 위치", "사용제한", "제한 내용", "제한 근거 위치", "회사 분류", "감사인 판단 분류", "판단 근거", "재분류 금액", ""];
    const tbody = h("tbody");
    cls.rows.forEach((r, i) => {
      const rp = `classify.rows.#${r.id}`;
      const dated = r.maturity_type === "만기 있음";
      tbody.append(h("tr", { dataset: { ref: `crow:${r.id}` } },
        h("td", { class: "num" }, i + 1),
        h("td", {}, input(`${rp}.item_id`, "text", { placeholder: "예: K02" })),
        h("td", {}, input(`${rp}.name`)),
        ...extra.map((x) => h("td", {}, input(`${rp}.${x.key}`, x.type, { options: x.options }))),
        h("td", {}, input(`${rp}.amount`, "amount")),
        h("td", {}, input(`${rp}.amount_loc`)),
        h("td", {}, input(`${rp}.maturity_type`, "choice", { options: ["만기 있음", "만기 없음"], rerender: true })),
        h("td", {}, dated ? input(`${rp}.acquired_date`, "date") : null),
        h("td", {}, dated ? input(`${rp}.maturity_date`, "date") : null),
        h("td", { class: "num diffcell", dataset: { calc: `cls:${r.id}:acq_days` } }),
        h("td", { class: "num diffcell", dataset: { calc: `cls:${r.id}:remain_days` } }),
        h("td", {}, dated ? input(`${rp}.terms_loc`) : null),
        h("td", {}, input(`${rp}.restricted`, "choice", { options: ["미확인", "없음", "있음"], rerender: true })),
        h("td", {}, r.restricted === "있음" ? input(`${rp}.restriction_note`, "text", { placeholder: "예: 차입금 담보 질권" }) : null),
        h("td", {}, input(`${rp}.restriction_loc`)),
        h("td", {}, input(`${rp}.company_class`, "choice", { options: classes })),
        h("td", {}, input(`${rp}.auditor_class`, "choice", { options: classes })),
        h("td", {}, input(`${rp}.basis`, "text", { placeholder: "판단에 쓴 조건" })),
        h("td", { class: "num diffcell", dataset: { calc: `cls:${r.id}:reclass` } }),
        h("td", {}, h("button", { class: "btn link", type: "button", onclick: () => mutate((d) => { d.classify.rows = d.classify.rows.filter((x) => x.id !== r.id); }) }, "삭제"))));
    });
    if (!cls.rows.length) tbody.append(h("tr", {}, h("td", { colspan: head.length, class: "sub" }, "검토 항목이 없습니다. 아래에서 추가하세요.")));
    box.append(h("div", { class: "tablewrap" }, h("table", { class: "recon classify" }, h("thead", {}, h("tr", {}, ...head.map((x) => h("th", {}, x)))), tbody)),
      h("div", {}, h("button", { class: "btn small", type: "button", onclick: () => mutate((d) => d.classify.rows.push({
        id: newId("c"), item_id: "", name: "", product_type: "", amount: "", amount_loc: "", maturity_type: "", acquired_date: "", maturity_date: "",
        terms_loc: "", restricted: "미확인", restriction_note: "", restriction_loc: "", company_class: "", auditor_class: "", basis: "", note: "" })) }, "+ 검토 항목 추가")),
      h("h2", {}, "분류별 합계"),
      h("div", { class: "totals" }, ...classes.flatMap((k) => [
        tot(`${k} — 회사 분류`, `clstot:${k}:company`),
        tot(`${k} — 감사인 판단`, `clstot:${k}:auditor`),
        tot(`${k} — 차이 (판단−회사)`, `clstot:${k}:diff`, true)])));
    return box;
  },

  scan() {
    return h("div", { class: "block" }, h("h2", {}, "명세서 스캔 (선택 단계)"),
      h("div", { class: "fields" },
        fieldBox("수행 여부", input("scan.status", "choice", { options: ["미결정", "수행", "해당 없음"] })),
        fieldBox("검토한 내용과 결과", input("scan.note", "textarea"), { wide: true, req: true, ui: "scan.show_note",
          help: "비경상으로 본 항목은 검토표 '비경상' 칸에 표시하고 이유를 적습니다." }),
        fieldBox("하지 않은 이유", input("scan.na_reason", "textarea"), { wide: true, req: true, ui: "scan.show_reason" })));
  },

  findings() {
    const box = h("div", { class: "block" });
    box.append(h("h2", {}, "계산에서 나온 차이"), h("div", { class: "cands", id: "cands" }));
    box.append(h("div", { class: "block-head" }, h("h2", {}, "발견 사항"),
      h("button", { class: "btn small", type: "button", onclick: () => addFinding({ link: "", title: "", amount: null }) }, "+ 다른 예외 직접 추가")));
    const cards = h("div", { class: "cards" });
    if (!S.data.findings.length) cards.append(h("p", { class: "sub" }, "기록된 발견 사항이 없습니다. 금액 차이가 없어도 다른 예외가 있으면 직접 추가하세요."));
    const mats = S.data.materials.map((m) => [m.id, `${LABEL[m.role]} · ${m.name}`]);
    for (const f of S.data.findings) {
      const p = `findings.#${f.id}`;
      cards.append(h("div", { class: "card" + (f.status !== "처리 완료" ? " attn" : ""), dataset: { ref: `finding:${f.id}` } },
        h("div", { class: "card-head" }, h("b", {}, f.title || "(제목 없음)"),
          h("div", { class: "chips" }, f.amount !== null && f.amount !== undefined && f.amount !== "" ? h("span", { class: "chip mark" }, fmt(f.amount) + "원") : null,
            h("span", { class: "chip", dataset: { linkstate: f.id } }),
            h("button", { class: "btn link", type: "button", onclick: () => mutate((d) => { d.findings = d.findings.filter((x) => x.id !== f.id); }) }, "삭제"))),
        h("div", { class: "fields" },
          fieldBox("제목", input(`${p}.title`), { wide: true }),
          fieldBox("사실 (금액·항목)", input(`${p}.fact`, "textarea"), { wide: true }),
          fieldBox("설명·재확인 근거", input(`${p}.explanation_type`, "choice", { options: ["없음", "담당자 설명만", "자료로 재확인"] })),
          fieldBox("상대자", input(`${p}.person`), { req: true, ui: `findings.${f.id}.show_person` }),
          fieldBox("일시", input(`${p}.discussed_at`, "text", { placeholder: "예: 2026-01-22 14:00" }), { req: true, ui: `findings.${f.id}.show_person` }),
          fieldBox("설명 내용", input(`${p}.explanation`, "textarea"), { req: true, wide: true, ui: `findings.${f.id}.show_person`,
            help: "구두 설명만으로는 적절한 근거가 되지 못합니다. 자료로 다시 확인하면 근거를 '자료로 재확인'으로 바꾸세요." }),
          fieldBox("재확인에 쓴 자료", input(`${p}.recheck_material_id`, "choice", { options: mats }), { req: true, ui: `findings.${f.id}.show_material` }),
          fieldBox("원인", input(`${p}.cause`, "textarea"), { wide: true }),
          fieldBox("후속 확인", input(`${p}.followup`, "textarea"), { wide: true, help: "요청한 자료, 요청일, 받으면 할 일" }),
          fieldBox("처리 상태", input(`${p}.status`, "choice", { options: ["미해결", "후속 확인 중", "처리 완료"], rerender: true }), { req: true }),
          fieldBox("처리 내용", input(`${p}.resolution`, "textarea"), { req: true, wide: true, ui: `findings.${f.id}.show_resolution` }),
          fieldBox("처리 근거", input(`${p}.resolution_basis`, "textarea"), { req: true, wide: true, ui: `findings.${f.id}.show_resolution` }))));
    }
    box.append(cards);
    return box;
  },

  open_items() {
    return h("div", { class: "block" }, h("h2", {}, "결론에 남을 미해결·남은 작업"),
      h("p", { class: "sub", style: "margin:0" }, "아래 목록은 엑셀 7번 '결론과 미해결 사항'에 그대로 출력됩니다."),
      h("ul", { class: "items", id: "open-items" }));
  },

  review_comments() {
    const box = h("div", { class: "block" }, h("div", { class: "block-head" }, h("h2", {}, "검토 의견"),
      h("button", { class: "btn small", type: "button", onclick: () => mutate((d) => d.review_comments.push({ id: newId("c"), by: "", date: "", text: "", response: "", resolved: false })) }, "+ 의견 추가")));
    if (!S.data.review_comments.length) box.append(h("p", { class: "sub" }, "검토 의견 없음"));
    for (const c of S.data.review_comments) {
      const p = `review_comments.#${c.id}`;
      box.append(h("div", { class: "card" + (c.resolved ? "" : " attn"), dataset: { ref: `comment:${c.id}` } }, h("div", { class: "fields" },
        fieldBox("작성자", input(`${p}.by`)), fieldBox("일자", input(`${p}.date`, "date")),
        fieldBox("의견", input(`${p}.text`, "textarea"), { wide: true }), fieldBox("답변", input(`${p}.response`, "textarea"), { wide: true }),
        h("label", { class: "check" }, input(`${p}.resolved`, "checkbox", { rerender: true }), "처리됨"))));
    }
    box.append(h("p", { class: "sub" }, "엑셀을 내려받아도 검토 완료로 바뀌지 않습니다."));
    return box;
  },
};

function tot(label, key, isDiff) {
  return h("div", { class: "total", dataset: { calc: key, diff: isDiff ? "1" : "" } }, h("span", {}, label), h("strong", {}, "—"));
}

function addFinding({ link, title, amount, fact }) {
  mutate((d) => d.findings.push({ id: newId("f"), link, title, amount, fact: fact || "", cause: "", explanation_type: "없음",
    person: "", discussed_at: "", explanation: "", recheck_material_id: "", followup: "", status: "미해결", resolution: "", resolution_basis: "" }));
}

function removeMaterial(id) {
  const used = (S.data.recon?.sets || []).some((s) => s.schedule_material_id === id) || S.data.recon?.gl_material_id === id ||
    S.data.classify?.schedule_material_id === id ||
    S.data.findings.some((f) => f.recheck_material_id === id) || S.data.materials.some((m) => m.original_id === id);
  if (used) { toast("대사·발견 사항·수정본에서 쓰는 자료는 삭제할 수 없습니다. 먼저 연결을 풀어주세요."); return; }
  mutate((d) => { d.materials = d.materials.filter((m) => m.id !== id); });
}

function startRevisedSet(matId) {
  const m = S.data.materials.find((x) => x.id === matId);
  const last = S.data.recon.sets[S.data.recon.sets.length - 1];
  mutate((d) => {
    const ns = { id: newId("s"), label: `수정본 명세서 (${m.name})`, schedule_material_id: matId, stated_total: "", stated_total_loc: "",
      rows: last.rows.map((r) => ({ ...r, id: newId("r"), schedule_amount: "", schedule_loc: "" })) };
    d.recon.sets.push(ns);
    S.setTab = ns.id;
  });
  toast("이전 대사 기록은 보존됩니다. 수정본 명세서의 금액과 위치를 새로 입력하세요.");
}

// ------------------------------------------------------------------ 계산 결과 반영
function applyComputed() {
  const c = S.computed; if (!c) return;
  const ui = c.ui;
  $$("[data-vis]").forEach((el) => { if (el.dataset.vis) el.hidden = c.visible[el.dataset.vis] === false; });
  $$("[data-ui]").forEach((el) => {
    const k = el.dataset.ui; if (!k) return;
    let v;
    if (k === "assertion_changed") v = ui.assertion_changed;
    else { const [grp, id, key] = k.split("."); v = key === undefined ? ui[grp]?.[id] : ui[grp]?.[id]?.[key]; }
    el.hidden = !v;
  });
  $$("[data-calc]").forEach((el) => {
    const parts = el.dataset.calc.split(":");
    let val;
    if (parts[0] === "cls") {
      const r = c.classify?.rows[parts[1]];
      val = r?.[parts[2]];
      const days = parts[2] !== "reclass";
      el.textContent = days && r?.no_maturity ? "해당 없음" : val === null || val === undefined ? "미입력" : fmt(val) + (days ? "일" : "");
      el.className = "num diffcell" + (val === null || val === undefined ? " na" : !days && val !== 0 ? " nz" : "");
      return;
    }
    if (parts[0] === "clstot") val = c.classify?.totals[parts[1]]?.[parts[2]];
    else if (parts[0] === "row") val = c.sets[parts[1]]?.rows[parts[2]]?.diff;
    else val = c.sets[parts[1]]?.[parts[2]];
    if (parts[0] === "row") {
      el.textContent = fmt(val);
      el.className = "num diffcell" + (val === null || val === undefined ? " na" : val !== 0 ? " nz" : "");
    } else {
      el.querySelector("strong").textContent = val === null || val === undefined ? "미입력" : fmt(val) + "원";
      el.classList.toggle("nz", !!el.dataset.diff && val !== null && val !== undefined && val !== 0);
    }
  });
  const cands = $("#cands");
  if (cands) {
    const open = c.diffs.filter((d) => !d.has_finding);
    put(cands, ...(open.length ? open.map((d) => h("div", { class: "cand", dataset: { ref: d.key } },
      h("span", {}, d.title), h("span", { class: "amt" }, fmt(d.amount) + "원"),
      S.readOnly ? null : h("button", { class: "btn small", type: "button", onclick: () => addFinding({ link: d.key, title: d.title, amount: d.amount, fact: factFor(d) }) }, "발견 사항으로 기록"))) :
      [h("p", { class: "sub", style: "margin:0" }, c.diffs.length ? "모든 차이에 발견 사항이 연결되어 있습니다." : "계산된 차이가 없습니다. 빈칸이 있으면 차이를 계산하지 않습니다.")]));
  }
  $$("[data-linkstate]").forEach((el) => {
    const s = ui.findings[el.dataset.linkstate]?.link_state;
    el.textContent = { open: "연결된 차이 있음", zero_or_blank: "연결된 차이가 현재 0 또는 미입력", missing: "연결된 대사 기록 없음", manual: "직접 추가" }[s] || "";
  });
  const rev = $('[data-region="revised"]');
  if (rev) put(rev, ...ui.unused_revised_schedules.map((mid) => {
    const m = S.data.materials.find((x) => x.id === mid);
    return h("div", { class: "cand" }, h("span", {}, `수정본 명세서 '${m.name}'을 입수했습니다. 이전 대사는 보존하고 수정본 기준으로 다시 대사하세요.`),
      S.readOnly ? null : h("button", { class: "btn small", type: "button", onclick: () => startRevisedSet(mid) }, "수정본으로 다시 대사"));
  }));
  const la = $("#linked-accounts");
  if (la && c.linked?.available) {
    const L = c.linked;
    put(la, L.rows.length ? h("div", { class: "tablewrap" }, h("table", { class: "ledger" },
      h("thead", {}, h("tr", {}, ...["계정", "표시 항목", "전기말", "수정후", "증감액", "증감률"].map((x) => h("th", {}, x)))),
      h("tbody", {}, ...L.rows.map((r) => h("tr", {},
        h("td", {}, h("a", { href: `#eng-${S.wp.engagement_id}-acct-${r.code}` }, `${r.code} ${r.name}`)), h("td", {}, r.fs_line),
        h("td", { class: "num" }, fmt(r.prior)), h("td", { class: "num" }, fmt(r.adjusted)), ...chgCells(r.change, r.change_rate, r.prior)))),
      h("tfoot", {}, h("tr", {}, h("td", { colspan: 2 }, "합계 (참조값)"), h("td", { class: "num" }, fmt(L.prior)),
        h("td", { class: "num" }, fmt(L.adjusted)), ...chgCells(L.change, L.change_rate, L.prior))))) :
      h("p", { class: "sub", style: "margin:0" }, "선택한 계정과목이 없습니다."));
  }
  const oi = $("#open-items");
  if (oi) put(oi, ...(c.open_items.length ? c.open_items.filter((i) => i.level !== "info").map((it) =>
    h("li", {}, h("button", { type: "button", class: "item " + it.level, onclick: () => goTo(it) }, h("span", {}, it.message, h("small", {}, it.category))))) :
    [h("li", { class: "sub" }, "남은 작업 없음")]));
  renderNav(); renderTodo(); renderTop();
}

function factFor(d) {
  if (d.key.startsWith("cls:")) {
    const r = S.computed.classify.rows[d.row];
    return `금액 ${fmt(r.amount)}원, 회사 분류 ${r.company}, 감사인 판단 분류 ${r.auditor}.` +
      (r.no_maturity ? " 만기 없음." : ` 취득→만기 ${fmt(r.acq_days)}일, 대상일→만기 ${fmt(r.remain_days)}일.`);
  }
  const st = S.computed.sets[d.set];
  if (d.row) { const r = st.rows[d.row]; return `명세서 ${fmt(r.schedule)}원, 보조부 ${fmt(r.subledger)}원, 차이 ${fmt(d.amount)}원.`; }
  if (d.key.endsWith("stated_vs_recalc")) return `명세서 표시 합계 ${fmt(st.stated_total)}원, 재계산 합계 ${fmt(st.recalc_total)}원.`;
  return `보조부 합계 ${fmt(st.subledger_total)}원, 총계정원장 잔액 ${fmt(st.gl_balance)}원.`;
}

// ------------------------------------------------------------------ 저장·출력·이력·잠금
async function saveDialog() {
  if (S.readOnly || !S.wp) return;
  const note = h("input", { type: "text", id: "save-note", placeholder: "예: 보조원장 대사 입력" });
  const reason = h("textarea", { id: "save-reason", rows: 2 });
  const body = [fieldBox("저장 메모 (선택)", note)];
  if (S.wp.locked) body.push(fieldBox("잠긴 조서 수정 이유", reason, { req: true }));
  const ok = await modal("저장", body, [["취소", false], ["저장", true, "primary"]]);
  if (!ok) return;
  try {
    const res = await api("POST", `/api/workpapers/${S.wp.id}/save`, { data: S.data, base_rev: S.wp.rev, note: note.value, change_reason: reason.value });
    load(res); renderEditor(); toast(`저장됨 · 리비전 ${res.rev}`);
    return true;
  } catch (e) {
    if (e.status === 409) {
      const re = await modal("저장 충돌", [h("p", {}, e.message)], [["닫기", false], ["최신본 다시 불러오기 (내 변경 버림)", true, "primary"]]);
      if (re) { S.dirty = false; openWp(S.wp.id); }
    } else modal("저장하지 못함", [h("p", { class: "err" }, e.message)], [["닫기", false]]);
    return false;
  }
}

async function exportDialog() {
  const url = (rev) => `/api/workpapers/${S.wp.id}/export.xlsx?rev=${rev}`;
  if (S.dirty) {
    const c = await modal("엑셀 내려받기", [h("p", {}, "저장하지 않은 변경은 엑셀에 들어가지 않습니다. 엑셀은 저장본 기준으로 만들어집니다.")],
      [["취소", null], ["마지막 저장본으로", "last"], ["저장 후 내려받기", "save", "primary"]]);
    if (!c) return;
    if (c === "save" && !(await saveDialog())) return;
  }
  location.href = url(S.wp.rev);
  toast("엑셀은 검토 완료를 뜻하지 않습니다. 검토 상태는 조서 기록을 따릅니다.");
}

async function historyDialog() {
  const { revisions, lock_events } = await api("GET", `/api/workpapers/${S.wp.id}/revisions`);
  const list = h("div", { class: "revs" }, ...revisions.map((r) => h("div", { class: "rev" },
    h("span", {}, h("b", {}, `리비전 ${r.rev_no}`), ` · ${r.saved_at.replace("T", " ")} · ${r.saved_by}`, r.note ? ` · ${r.note}` : "",
      r.change_reason ? h("div", { class: "sub" }, `잠금 중 수정 이유: ${r.change_reason}`) : null),
    h("span", { class: "chips" },
      h("a", { class: "btn small", href: r.rev_no === revisions[0].rev_no ? `#wp-${S.wp.id}` : `#wp-${S.wp.id}-r${r.rev_no}`, onclick: () => ($("#modal").hidden = true) }, "보기"),
      h("a", { class: "btn small", href: `/api/workpapers/${S.wp.id}/export.xlsx?rev=${r.rev_no}` }, "엑셀")))));
  const locks = lock_events.length ? h("div", {}, h("h3", { style: "font-size:14px;margin:8px 0 4px" }, "잠금 기록"),
    ...lock_events.map((l) => h("div", { class: "sub" }, `${l.at.replace("T", " ")} · ${l.locked ? "잠금" : "해제"} · ${l.by} · ${l.reason}`))) : null;
  modal("저장 이력", [h("p", { class: "sub" }, "저장할 때마다 리비전이 쌓입니다. 이전 리비전은 읽기 전용으로 볼 수 있습니다. 엑셀에는 선택한 저장본만 들어갑니다."), list, locks], [["닫기", false]]);
}

async function lockDialog() {
  const reason = h("textarea", { id: "lock-reason", rows: 2 });
  const locking = !S.wp.locked;
  const ok = await modal(locking ? "편집 잠금" : "잠금 해제", [
    h("p", { class: "sub" }, "업무용 잠금입니다. 최종 감사파일 취합이나 법정 보존 기능이 아닙니다. 잠긴 조서도 수정 이유를 적으면 저장할 수 있고, 이유는 이력에 남습니다."),
    fieldBox("사유", reason, { req: true })], [["취소", false], [locking ? "잠그기" : "해제", true, "primary"]]);
  if (!ok) return;
  if (S.dirty) { toast("먼저 저장하세요."); return; }
  try { await api("POST", `/api/workpapers/${S.wp.id}/lock`, { locked: locking, reason: reason.value }); await openWp(S.wp.id); toast(locking ? "잠금" : "잠금 해제"); }
  catch (e) { modal("처리하지 못함", [h("p", { class: "err" }, e.message)], [["닫기", false]]); }
}

// ------------------------------------------------------------------ 재무제표 → 정산표 → 계정원장 → 분개장
const won = (n) => (n === null || n === undefined ? "미입력" : Number(n).toLocaleString("ko-KR"));
// 증감액·증감률: 증가 ▲, 감소 ▼. 계산은 서버(engine)가 하고 화면은 표시만 한다.
function chgText(v, unit = "") {
  if (v === null || v === undefined) return null;
  const n = Number(v);
  const body = unit === "%" ? `${Math.abs(n).toFixed(1)}%` : Math.abs(n).toLocaleString("ko-KR");
  return n > 0 ? `▲ ${body}` : n < 0 ? `▼ ${body}` : body;
}
function chgCells(amount, rate, prior) {
  const dir = (v) => (v === null || v === undefined ? " na" : v > 0 ? " up" : v < 0 ? " down" : " zero");
  return [
    h("td", { class: "num chg" + dir(amount) }, chgText(amount) ?? "미입력"),
    h("td", { class: "num chg" + dir(rate ?? (prior === 0 && amount ? amount : null)), title: rate === null || rate === undefined ? (prior === 0 ? "전기가 0원이라 증감률을 계산하지 않음" : "계산할 수 없음") : null },
      chgText(rate, "%") ?? (prior === 0 && amount ? "신규" : "—")),
  ];
}
const LEDGER_STEPS = [["fs", "재무제표"], ["tb", "정산표"], ["acct", "계정원장"], ["je", "분개장"]];

async function ledgerView(eid, view, arg) {
  S.wp = null; S.dirty = false; renderTop();
  const res = await api("GET", `/api/engagements/${eid}/ledger`);
  const E = res.engagement;
  put($("#crumb"), h("b", {}, E.company), ` · 보고기간 종료일 ${E.period_end} · ${E.currency}·${E.unit}`);
  put($("#chips"), E.is_sample ? h("span", { class: "chip sample" }, "가상 데이터") : null,
    res.ledger ? h("span", { class: "chip" }, h("i", {}, "자료"), res.ledger._source) : null);
  if (!res.ledger) {
    put($("#app"), h("section", { class: "paper step" }, h("h1", {}, "정산표 없음"), h("p", {}, "이 감사건에는 정산표·분개장이 없습니다."), h("a", { href: "#" }, "조서 목록으로")));
    return;
  }
  const L = res.ledger, C = res.computed;
  const byCode = Object.fromEntries(L.accounts.map((a) => [a.code, a]));
  const wpsFor = (codes) => E.workpapers.filter((w) => w.linked_accounts.some((c) => codes.includes(c)));
  const base = `#eng-${eid}`;
  const trail = [h("a", { href: base }, "재무제표")];
  let body;
  if (view === "fs") body = fsView();
  else if (view === "tb") body = tbView(arg);
  else if (view === "acct") body = await acctView(arg);
  else body = jeView(arg);
  put($("#app"), h("div", { class: "ledger-page" },
    h("nav", { class: "flow", "aria-label": "탐색 단계" }, ...LEDGER_STEPS.map(([k, label], i) => [
      i ? h("span", { class: "arrow", "aria-hidden": "true" }, "→") : null,
      k === view || k === "acct" ? h("span", { class: "flowstep" + (k === view ? " on" : ""), title: k === "acct" ? "정산표에서 계정과목을 고르면 열립니다" : null }, label) :
        h("a", { class: "flowstep", href: k === "fs" ? base : `${base}-${k}` }, label)])),
    h("div", { class: "trail sub" }, ...trail.flatMap((t, i) => (i ? [" › ", t] : [t]))),
    body,
    h("p", { class: "sub" }, "정산표·분개장은 감사건 단위 참조 자료입니다. 금액은 계정의 정상 잔액 방향 기준이며, 손익 계정의 '전기말' 열은 전기 금액(비교용)입니다.")));

  function wpLinks(codes, short) {
    const wps = wpsFor(codes);
    return wps.length ? h("div", { class: "chips" }, ...wps.map((w) => h("a", { class: "chip", href: `#wp-${w.id}`, title: w.title },
      short ? w.wp_no || "조서" : `${w.wp_no || "조서"} ${w.title}`))) :
      h("span", { class: "sub" }, "연결된 조서 없음");
  }

  function fsView() {
    const sec = (stmt) => {
      const lines = C.fs_lines.filter((l) => l.statement === stmt);
      const cats = [...new Set(lines.map((l) => l.category))];
      const rows = [];
      for (const cat of cats) {
        rows.push(h("tr", { class: "cat" }, h("td", { colspan: 7 }, cat)));
        for (const l of lines.filter((x) => x.category === cat)) {
          rows.push(h("tr", {},
            h("td", {}, h("a", { href: `${base}-tb-${encodeURIComponent(l.name)}` }, l.name),
              l.includes_net_income ? h("small", { class: "sub" }, ` (당기순이익 ${won(C.income.net_income)} 포함)`) : null),
            h("td", { class: "num" }, won(l.prior)), h("td", { class: "num" }, won(l.current)),
            ...chgCells(l.change, l.change_rate, l.prior),
            h("td", { class: "num sub" }, `${l.accounts.length}개`), h("td", {}, wpLinks(l.accounts))));
        }
      }
      return rows;
    };
    const bs = C.bs_totals, inc = C.income;
    const tot = (label, p, c, chg, rate) => h("tr", { class: "tot" }, h("td", {}, label), h("td", { class: "num" }, won(p)),
      h("td", { class: "num" }, won(c)), ...chgCells(chg, rate, p), h("td"), h("td"));
    const check = (label, p, c) => h("tr", { class: "tot" + (p !== 0 || c !== 0 ? " bad" : "") }, h("td", {}, label),
      h("td", { class: "num" }, won(p)), h("td", { class: "num" }, won(c)), h("td", { colspan: 4 }, p === 0 && c === 0 ? "일치" : "불일치"));
    const head = h("thead", {}, h("tr", {}, ...["표시 항목", "전기", "당기", "증감액", "증감률", "계정", "관련 조서"].map((x) => h("th", {}, x))));
    return h("div", { class: "grid2" },
      h("section", { class: "paper step" }, h("h1", {}, "재무상태표"),
        h("p", { class: "sub", style: "margin:0" }, "표시 항목을 누르면 그 항목을 이루는 정산표 계정과목으로 내려갑니다."),
        h("div", { class: "tablewrap" }, h("table", { class: "ledger" }, head, h("tbody", {}, ...sec("재무상태표"),
          tot("자산 총계", bs.prior.자산, bs.current.자산, bs.change.자산, bs.change_rate.자산),
          tot("부채와자본 총계", bs.prior.부채와자본, bs.current.부채와자본, bs.change.부채와자본, bs.change_rate.부채와자본),
          check("자산 − (부채+자본)", bs.prior.diff, bs.current.diff))))),
      h("section", { class: "paper step" }, h("h1", {}, "손익계산서"),
        h("div", { class: "tablewrap" }, h("table", { class: "ledger" }, head.cloneNode(true), h("tbody", {}, ...sec("손익계산서"),
          tot("당기순이익", inc.net_income_prior, inc.net_income, inc.net_income_change, inc.net_income_change_rate))))));
  }

  function tbView(line) {
    const accts = line ? L.accounts.filter((a) => a.fs_line === line) : L.accounts;
    if (line) trail.push(h("span", {}, line));
    else trail.push(h("span", {}, "정산표 전체"));
    const rows = accts.map((a) => {
      const c = C.accounts[a.code];
      const ok = c.unadjusted_vs_journal === 0 && c.adjustment_vs_journal === 0 && c.adjusted_check === 0;
      return h("tr", {},
        h("td", { class: "nowrap" }, h("a", { href: `${base}-acct-${a.code}` }, `${a.code} ${a.name}`)), h("td", { class: "sub" }, `${a.fs_line} · ${a.category}`),
        h("td", { class: "num" }, won(c.prior)), h("td", { class: "num" }, won(c.unadjusted)), h("td", { class: "num" }, won(c.adjustment)),
        h("td", { class: "num" }, won(c.adjusted)), ...chgCells(c.change, c.change_rate, c.prior),
        h("td", { class: ok ? "okc" : "badc", title: "기초 + 일반 분개 = 수정전, 수정분개 합계 = 수정분개, 수정전 + 수정분개 = 수정후" },
          ok ? "일치" : `수정전 차이 ${won(c.unadjusted_vs_journal)} / 수정분개 차이 ${won(c.adjustment_vs_journal)}`),
        h("td", {}, wpLinks([a.code], true)));
    });
    const ts = line ? C.fs_lines.find((l) => l.name === line)?.tb_sums : null;
    const foot = ts ? h("tr", { class: "tot" }, h("td", { colspan: 2 }, `${line} 합계`), ...["prior", "unadjusted", "adjustment", "adjusted"].map((k) =>
      h("td", { class: "num" }, won(ts[k]))), ...chgCells(ts.change, ts.change_rate, ts.prior), h("td"), h("td")) : null;
    const tb = C.tb_totals;
    return h("section", { class: "paper step" },
      h("div", { class: "block-head" }, h("h1", {}, line ? `정산표 — ${line}` : "정산표"),
        line ? h("a", { class: "btn small", href: `${base}-tb` }, "정산표 전체") : null),
      h("p", { class: "sub", style: "margin:0" }, "증감액 = 수정후 − 전기말, 증감률 = 증감액 ÷ 전기말. ▲ 증가, ▼ 감소. '분개장 대조'는 분개장에서 다시 쌓은 금액과 정산표가 맞는지입니다. 계정과목을 누르면 계정원장으로 내려갑니다."),
      h("div", { class: "tablewrap" }, h("table", { class: "ledger wide" },
        h("thead", {}, h("tr", {}, ...["계정과목", "표시 항목 · 분류", "전기말", "수정전", "수정분개", "수정후", "증감액", "증감률", "분개장 대조", "관련 조서"].map((x) => h("th", {}, x)))),
        h("tbody", {}, ...rows), foot ? h("tfoot", {}, foot) : null)),
      line ? null : h("div", { class: "totals" },
        ...[["unadjusted", "수정전"], ["adjusted", "수정후"]].flatMap(([k, lab]) => [
          h("div", { class: "total" }, h("span", {}, `${lab} 차변 합계`), h("strong", {}, won(tb[k].debit))),
          h("div", { class: "total" }, h("span", {}, `${lab} 대변 합계`), h("strong", {}, won(tb[k].credit))),
          h("div", { class: "total" + (tb[k].diff ? " nz" : "") }, h("span", {}, `${lab} 차변 − 대변`), h("strong", {}, won(tb[k].diff)))])));
  }

  async function acctView(code) {
    const a = byCode[code];
    if (!a) return h("section", { class: "paper step" }, h("p", { class: "err" }, `정산표에 없는 계정과목: ${code}`));
    trail.push(h("a", { href: `${base}-tb-${encodeURIComponent(a.fs_line)}` }, a.fs_line), h("span", {}, `${a.code} ${a.name}`));
    const G = await api("GET", `/api/engagements/${eid}/ledger/accounts/${encodeURIComponent(code)}`);
    const c = G.calc;
    const rows = [h("tr", { class: "cat" }, h("td", {}, ""), h("td", {}, ""), h("td", {}, ""), h("td", {}, c.is_bs ? "기초 잔액 (전기말)" : "기초 (손익 계정은 0)"),
      h("td"), h("td"), h("td", { class: "num" }, won(c.opening)))];
    for (const ln of G.lines) rows.push(h("tr", { class: ln.kind === "수정분개" ? "adj" : "" },
      h("td", {}, ln.date), h("td", {}, h("a", { href: `${base}-je-${encodeURIComponent(ln.je_no)}` }, ln.je_no)), h("td", { class: "sub" }, ln.kind),
      h("td", {}, ln.description), h("td", { class: "num" }, ln.debit ? won(ln.debit) : ""), h("td", { class: "num" }, ln.credit ? won(ln.credit) : ""),
      h("td", { class: "num" }, won(ln.balance))));
    return h("section", { class: "paper step" },
      h("h1", {}, `계정원장 — ${a.code} ${a.name}`),
      h("div", { class: "totals" },
        h("div", { class: "total" }, h("span", {}, c.is_bs ? "전기말" : "전기 금액(비교용)"), h("strong", {}, won(c.prior))),
        h("div", { class: "total" }, h("span", {}, "정산표 수정후"), h("strong", {}, won(c.adjusted))),
        h("div", { class: "total chgbox" + (c.change > 0 ? " up" : c.change < 0 ? " down" : "") }, h("span", {}, "증감액"), h("strong", {}, chgText(c.change) ?? "미입력")),
        h("div", { class: "total chgbox" + (c.change_rate > 0 ? " up" : c.change_rate < 0 ? " down" : "") }, h("span", {}, "증감률"),
          h("strong", {}, chgText(c.change_rate, "%") ?? (c.prior === 0 && c.change ? "신규" : "—"))),
        h("div", { class: "total" }, h("span", {}, "원장 기말 (분개 누적)"), h("strong", {}, won(G.closing))),
        h("div", { class: "total" + (G.closing_vs_adjusted ? " nz" : "") }, h("span", {}, "원장 기말 − 정산표 수정후"), h("strong", {}, won(G.closing_vs_adjusted)))),
      h("div", { class: "block" }, h("h2", {}, "이 계정과목을 다루는 조서·명세서"), wpLinks([a.code])),
      h("div", { class: "tablewrap" }, h("table", { class: "ledger" },
        h("thead", {}, h("tr", {}, ...["일자", "전표", "구분", "적요", "차변", "대변", `잔액 (${c.side === 1 ? "차변" : "대변"} 기준)`].map((x) => h("th", {}, x)))),
        h("tbody", {}, ...rows))),
      h("p", { class: "sub", style: "margin:0" }, "전표 번호를 누르면 분개장의 해당 전표로 갑니다. 수정분개는 일반 분개 뒤에 표시합니다."));
  }

  function jeView(no) {
    trail.push(h("span", {}, no ? `전표 ${no}` : "분개장 전체"));
    const groups = Object.values(C.journal).filter((g) => !no || g.je_no === no);
    const lines = Object.fromEntries(L.journal.map((ln) => [ln.id, ln]));
    const rows = [];
    for (const g of groups) {
      g.lines.forEach((id, i) => {
        const ln = lines[id], a = byCode[ln.code];
        rows.push(h("tr", { class: (i === 0 ? "first " : "") + (g.kind === "수정분개" ? "adj" : "") },
          h("td", {}, i === 0 ? h("a", { href: `${base}-je-${encodeURIComponent(g.je_no)}` }, g.je_no) : ""), h("td", {}, i === 0 ? g.date : ""),
          h("td", { class: "sub" }, i === 0 ? g.kind : ""),
          h("td", {}, h("a", { href: `${base}-acct-${ln.code}` }, a ? `${ln.code} ${a.name}` : `${ln.code} (정산표에 없음)`)),
          h("td", {}, ln.description), h("td", { class: "num" }, ln.debit ? won(ln.debit) : ""), h("td", { class: "num" }, ln.credit ? won(ln.credit) : "")));
      });
      rows.push(h("tr", { class: "tot" + (g.diff ? " bad" : "") }, h("td", { colspan: 5 }, g.diff ? `${g.je_no} 차대 불일치 ${won(g.diff)}` : `${g.je_no} 합계`),
        h("td", { class: "num" }, won(g.debit)), h("td", { class: "num" }, won(g.credit))));
    }
    return h("section", { class: "paper step" },
      h("div", { class: "block-head" }, h("h1", {}, no ? `분개장 — 전표 ${no}` : "분개장"),
        no ? h("a", { class: "btn small", href: `${base}-je` }, "분개장 전체") : null),
      h("p", { class: "sub", style: "margin:0" }, "계정과목을 누르면 그 계정원장으로 갑니다."),
      h("div", { class: "tablewrap" }, h("table", { class: "ledger" },
        h("thead", {}, h("tr", {}, ...["전표", "일자", "구분", "계정과목", "적요", "차변", "대변"].map((x) => h("th", {}, x)))),
        h("tbody", {}, ...rows))));
  }
}
