"use strict";
(() => {
  const root = document.getElementById("app");
  let key = sessionStorage.getItem("ragleap_key") || "";
  let tab = "overview";
  let timer = null;
  let armed = false;
  let view = null;
  let stamp = null;
  const tabButtons = {};
  const expanded = new Set();
  const TABS = [["overview", "Overview"], ["approvals", "Approvals"], ["runs", "Agent runs"], ["log", "Activity"]];

  // All dynamic text goes in as text nodes; nothing here ever builds HTML from data.
  const add = (el, kid) => {
    if (kid === null || kid === undefined || kid === false) return;
    if (Array.isArray(kid)) { kid.forEach((k) => add(el, k)); return; }
    el.appendChild(kid.nodeType ? kid : document.createTextNode(String(kid)));
  };
  const h = (tag, props, ...kids) => {
    const el = document.createElement(tag);
    Object.entries(props || {}).forEach(([k, v]) => {
      if (k === "class") el.className = v;
      else if (k === "on") Object.entries(v).forEach(([ev, fn]) => el.addEventListener(ev, fn));
      else if (k === "disabled") el.disabled = !!v;
      else if (["type", "placeholder", "title", "autocomplete"].includes(k)) el.setAttribute(k, String(v));
    });
    kids.forEach((kid) => add(el, kid));
    return el;
  };
  const clip = (text, n) => { const s = String(text === null || text === undefined ? "" : text); return s.length > n ? s.slice(0, n) + " ..." : s; };
  const ago = (iso) => {
    if (!iso) return "never";
    const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
    if (s < 90) return s + "s ago";
    if (s < 5400) return Math.round(s / 60) + " min ago";
    if (s < 129600) return Math.round(s / 3600) + " h ago";
    return Math.round(s / 86400) + " d ago";
  };
  const when = (iso) => (iso ? new Date(iso).toLocaleString() : "-");
  const num = (n) => Number(n || 0).toLocaleString();
  const toggle = (id) => { if (expanded.has(id)) expanded.delete(id); else expanded.add(id); refresh(); };

  const api = async (method, path, body) => {
    const init = { method, cache: "no-store", headers: { "x-api-key": key } };
    if (body !== undefined) { init.headers["Content-Type"] = "application/json"; init.body = JSON.stringify(body); }
    const res = await fetch(path, init);
    if (res.status === 401) { lock("That key was not accepted."); throw new Error("unauthorized"); }
    let data = null;
    try { data = await res.json(); } catch (e) { data = null; }
    if (!res.ok) throw new Error((data && data.detail) || ("Request failed (" + res.status + ")"));
    return data;
  };

  const lock = (msg) => {
    key = "";
    sessionStorage.removeItem("ragleap_key");
    if (timer) { clearInterval(timer); timer = null; }
    showLogin(msg);
  };

  const showLogin = (msg) => {
    root.replaceChildren();
    const input = h("input", { type: "password", placeholder: "API key", autocomplete: "off" });
    const go = () => { key = input.value.trim(); if (!key) return; sessionStorage.setItem("ragleap_key", key); start(); };
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
    add(root, h("section", { class: "login" },
      h("h1", null, "RagLeap AI Office"),
      h("p", null, "Enter the API key for this server. It stays in this browser tab only."),
      input,
      h("button", { type: "button", on: { click: go } }, "Open"),
      msg ? h("p", { class: "err" }, msg) : null));
    input.focus();
  };

  const stat = (label, value, sub, warn) => h("div", { class: "card" + (warn ? " warn" : "") },
    h("div", { class: "lab" }, label), h("div", { class: "big" }, value), sub ? h("div", { class: "sub" }, sub) : null);
  const counts = (o) => { const k = Object.keys(o || {}); return k.length ? k.map((s) => s + " " + o[s]).join(" / ") : "none"; };

  const renderOverview = (ov) => {
    const a = ov.autonomy || {};
    const t = ov.triggers || {};
    const r = ov.roles || {};
    const u = ov.usage || {};
    return h("div", { class: "grid" },
      stat("Waiting for approval", ov.pending_approvals || 0, a.approval_target_set ? "you get a Telegram ping" : "no approval ping set up", (ov.pending_approvals || 0) > 0),
      stat("Autonomy mode", a.mode || "?", a.mode === "full" ? "actions run WITHOUT asking" : (a.mode === "off" ? "actions are skipped" : "actions wait for you"), a.mode === "full"),
      stat("AI employees", r.active || 0, "of " + (r.total || 0) + " roles"),
      stat("Agent runs", counts(ov.runs), ""),
      stat("Tasks", counts(ov.tasks), ""),
      stat("Triggers", (t.active || 0) + " active", t.next_run_at ? "next " + when(t.next_run_at) : "none scheduled"),
      stat("Tokens today", num(u.day_tokens), "this month " + num(u.month_tokens)));
  };

  const approvalButton = (label, kind, path, msg) => {
    const b = h("button", { type: "button", class: kind }, label);
    let timeout = null;
    b.addEventListener("click", async () => {
      if (!b.dataset.armed) {
        b.dataset.armed = "1";
        armed = true;
        b.textContent = "Click again to confirm";
        timeout = setTimeout(() => { delete b.dataset.armed; b.textContent = label; armed = false; }, 6000);
        return;
      }
      clearTimeout(timeout);
      armed = false;
      b.disabled = true;
      try {
        const r = await api("POST", path);
        msg.textContent = r.result || "Done.";
        setTimeout(refresh, 800);
      } catch (e) {
        msg.textContent = "Failed: " + clip(e.message, 120);
        b.disabled = false;
      }
    });
    return b;
  };

  const approvalCard = (p) => {
    const msg = h("span", { class: "sub" }, "");
    const base = "/autonomy/pending/" + encodeURIComponent(p.action_id);
    return h("article", { class: "item" },
      h("div", { class: "row" }, h("strong", null, p.action_type), p.role ? h("span", { class: "tag" }, p.role) : null,
        h("span", { class: "tag" }, p.channel), h("span", { class: "sub" }, ago(p.created_at))),
      p.target ? h("div", { class: "sub" }, "target: " + clip(p.target, 200)) : null,
      h("pre", null, p.content),
      h("div", { class: "row" }, approvalButton("Approve", "ok", base + "/approve", msg),
        approvalButton("Reject", "bad", base + "/reject", msg), msg));
  };
  const renderApprovals = (items) => (items.length
    ? h("div", { class: "list" }, items.map(approvalCard))
    : h("p", { class: "empty" }, "Nothing is waiting for approval."));

  const runCard = (r) => {
    const isOpen = expanded.has(r.id);
    const statusClass = r.status === "done" ? "ok" : (r.status === "waiting_approval" ? "warn" : (r.status === "running" ? "" : "bad"));
    const body = isOpen ? h("div", null,
      r.summary ? h("p", null, r.summary) : null,
      (r.steps || []).map((s, i) => h("div", { class: "step" },
        h("div", { class: "row" }, h("strong", null, (i + 1) + ". " + s.tool), h("span", { class: "tag" }, s.status),
          s.forced_approval ? h("span", { class: "tag warn" }, "approval forced") : null),
        s.target ? h("div", { class: "sub" }, clip(s.target, 200)) : null,
        s.observation ? h("pre", null, s.observation) : null))) : null;
    return h("article", { class: "item" },
      h("div", { class: "row click", on: { click: () => toggle(r.id) } },
        h("strong", null, clip(r.query, 90)), h("span", { class: "tag " + statusClass }, r.status),
        r.tainted ? h("span", { class: "tag warn" }, "saw web content") : null,
        h("span", { class: "sub" }, (r.steps || []).length + " step(s), " + ago(r.updated_at))),
      body);
  };
  const renderRuns = (runs) => (runs.length ? h("div", { class: "list" }, runs.map(runCard)) : h("p", { class: "empty" }, "No agent runs yet."));

  const logCard = (r) => {
    const id = "log" + r.id;
    const isOpen = expanded.has(id);
    return h("article", { class: "item" },
      h("div", { class: "row click", on: { click: () => toggle(id) } },
        h("strong", null, r.action_type), r.role ? h("span", { class: "tag" }, r.role) : null,
        h("span", { class: "tag " + (r.approved ? "ok" : "bad") }, r.approved ? "approved" : "rejected"),
        h("span", { class: "sub" }, when(r.created_at))),
      h("div", { class: "sub" }, clip(r.result, isOpen ? 4000 : 140)),
      isOpen ? h("pre", null, r.content) : null);
  };
  const renderLog = (rows) => (rows.length ? h("div", { class: "list" }, rows.map(logCard)) : h("p", { class: "empty" }, "No actions logged yet."));

  const refresh = async () => {
    if (armed || !view) return;
    try {
      const ov = await api("GET", "/overview");
      const n = ov.pending_approvals || 0;
      tabButtons.approvals.textContent = n ? "Approvals (" + n + ")" : "Approvals";
      Object.keys(tabButtons).forEach((id) => tabButtons[id].classList.toggle("on", id === tab));
      let content;
      if (tab === "overview") content = renderOverview(ov);
      else if (tab === "approvals") content = renderApprovals((await api("GET", "/autonomy/pending")).pending);
      else if (tab === "runs") content = renderRuns((await api("GET", "/agent-runs?limit=30")).runs);
      else content = renderLog((await api("GET", "/autonomy/log?limit=60")).log);
      view.replaceChildren(content);
      stamp.textContent = "updated " + new Date().toLocaleTimeString();
    } catch (e) {
      if (String(e.message) !== "unauthorized") stamp.textContent = "error: " + clip(e.message, 80);
    }
  };

  const buildShell = () => {
    root.replaceChildren();
    stamp = h("span", { class: "stamp" }, "");
    const nav = h("nav", null);
    TABS.forEach(([id, label]) => {
      const b = h("button", { type: "button", class: "tab", on: { click: () => { tab = id; armed = false; refresh(); } } }, label);
      tabButtons[id] = b;
      nav.appendChild(b);
    });
    view = h("main", null);
    add(root, h("header", null, h("strong", null, "RagLeap AI Office"), nav, stamp,
      h("button", { type: "button", class: "ghost", on: { click: () => lock("") } }, "Lock")));
    add(root, view);
  };

  const start = async () => {
    root.replaceChildren(h("p", { class: "empty" }, "Connecting..."));
    try { await api("GET", "/overview"); } catch (e) {
      if (String(e.message) !== "unauthorized") showLogin("Could not reach the server: " + clip(e.message, 100));
      return;
    }
    buildShell();
    await refresh();
    if (timer) clearInterval(timer);
    timer = setInterval(refresh, 10000);
  };

  if (key) start(); else showLogin("");
})();
