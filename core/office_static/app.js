"use strict";
(() => {
  const root = document.getElementById("app");
  // One-click login link: /office#key=... stores the key for this tab and removes it from the
  // address bar. A URL fragment is never sent to the server.
  const linkKey = (() => {
    const m = /^#key=([A-Za-z0-9._~%-]+)$/.exec(location.hash);
    if (!m) return "";
    try { return decodeURIComponent(m[1]); } catch (e) { return ""; }
  })();
  if (linkKey) {
    sessionStorage.setItem("ragleap_key", linkKey);
    history.replaceState(null, "", location.pathname + location.search);
  }
  let key = sessionStorage.getItem("ragleap_key") || "";
  let tab = "overview";
  let timer = null;
  let armed = false;
  let view = null;
  let stamp = null;
  const tabButtons = {};
  const expanded = new Set();
  const TABS = [["setup", "Setup"], ["overview", "Overview"], ["approvals", "Approvals"], ["employees", "Employees"], ["tasks", "Tasks"], ["runs", "Agent runs"], ["log", "Activity"], ["settings", "Settings"]];

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
      else if (k === "value") el.value = String(v);
      else if (["type", "placeholder", "title", "autocomplete", "rows", "maxlength"].includes(k)) el.setAttribute(k, String(v));
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
    taskFormEl = null;
    boardEl = null;
    settingsEl = null;
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

  const meter = (used, limit) => (limit > 0 ? Math.min(100, Math.round((used * 100) / limit)) + "% of " + num(limit) : "no cap");
  const roleCard = (r) => {
    const id = "role" + r.role;
    const isOpen = expanded.has(id);
    return h("article", { class: "item" },
      h("div", { class: "row click", on: { click: () => toggle(id) } },
        h("strong", null, r.display_name || r.role),
        r.sensitive ? h("span", { class: "tag warn" }, "sensitive") : null,
        h("span", { class: "tag " + (r.is_active ? "ok" : "bad") }, r.is_active ? "active" : "off"),
        r.open_tasks ? h("span", { class: "tag" }, r.open_tasks + " open task(s)") : null,
        h("span", { class: "sub" }, "today " + num(r.day_used) + " | month " + num(r.month_used))),
      isOpen ? h("div", null,
        r.skills_summary ? h("p", null, r.skills_summary) : null,
        h("div", { class: "sub" }, "skills: " + ((r.skill_tags || []).join(", ") || "none")),
        h("div", { class: "sub" }, "channels: " + ((r.channels || []).join(", ") || "none")),
        h("div", { class: "sub" }, "daily budget: " + meter(r.day_used, r.day_limit) + " | monthly: " + meter(r.month_used, r.month_limit)),
        h("div", { class: "sub" }, "last learned: " + (r.last_learned_at ? when(r.last_learned_at) : "never"))) : null);
  };
  const renderOrg = (org) => h("div", { class: "list" },
    h("div", { class: "card" },
      h("div", { class: "row" }, h("strong", null, "You (owner)"), h("span", { class: "tag" }, "autonomy: " + org.owner.mode)),
      h("div", { class: "sub" }, org.router.note)),
    org.departments.map((d) => h("section", { class: "dept" },
      h("h2", null, d.name + " (" + d.roles.length + ")"), h("div", { class: "list" }, d.roles.map(roleCard)))));

  const TASK_COLS = [["open", "Open"], ["in_progress", "In progress"], ["blocked", "Blocked"], ["done", "Done"]];
  let taskFormEl = null;
  let boardEl = null;
  const moveTask = async (t, status, msg) => {
    try { await api("PATCH", "/tasks/" + encodeURIComponent(t.id), { status: status }); refresh(); }
    catch (e) { msg.textContent = "Failed: " + clip(e.message, 100); }
  };
  const taskCard = (t) => {
    const msg = h("span", { class: "sub" }, "");
    const i = TASK_COLS.findIndex((c) => c[0] === t.status);
    const btns = [];
    if (i > 0) btns.push(h("button", { type: "button", class: "ghost", on: { click: () => moveTask(t, TASK_COLS[i - 1][0], msg) } }, "< " + TASK_COLS[i - 1][1]));
    if (i >= 0 && i < TASK_COLS.length - 1) btns.push(h("button", { type: "button", on: { click: () => moveTask(t, TASK_COLS[i + 1][0], msg) } }, TASK_COLS[i + 1][1] + " >"));
    return h("article", { class: "item" },
      h("strong", null, clip(t.title, 120)),
      h("div", { class: "row" },
        h("span", { class: "tag " + (t.priority === "urgent" ? "bad" : (t.priority === "high" ? "warn" : "")) }, t.priority),
        h("span", { class: "tag" }, t.assigned_role || "unassigned"), h("span", { class: "sub" }, ago(t.created_at))),
      t.description ? h("div", { class: "sub" }, clip(t.description, 220)) : null,
      t.result ? h("div", { class: "sub" }, "result: " + clip(t.result, 220)) : null,
      h("div", { class: "row" }, btns, msg));
  };
  const buildTaskForm = (roleNames) => {
    const title = h("input", { type: "text", placeholder: "New task title", maxlength: 200 });
    const desc = h("textarea", { rows: 2, placeholder: "Details (optional)" });
    const prio = h("select", null, ["normal", "low", "high", "urgent"].map((p) => h("option", { value: p }, p)));
    const who = h("select", null, h("option", { value: "" }, "unassigned"), roleNames.map((r) => h("option", { value: r }, r)));
    const msg = h("span", { class: "sub" }, "");
    const go = h("button", { type: "button", class: "ok", on: { click: async () => {
      const body = { title: title.value.trim(), description: desc.value.trim(), priority: prio.value };
      if (who.value) body.assigned_role = who.value;
      if (!body.title) { msg.textContent = "Give the task a title."; return; }
      try { await api("POST", "/tasks", body); title.value = ""; desc.value = ""; msg.textContent = "Created."; refresh(); }
      catch (e) { msg.textContent = "Failed: " + clip(e.message, 100); }
    } } }, "Add task");
    return h("div", { class: "card" }, h("div", { class: "row" }, title, prio, who), desc, h("div", { class: "row" }, go, msg));
  };
  const refreshTasks = async () => {
    if (!taskFormEl) {
      const roleNames = (await api("GET", "/employees?active_only=true")).roles.map((r) => r.role);
      taskFormEl = buildTaskForm(roleNames);
      boardEl = h("div", null);
    }
    if (view.firstChild !== taskFormEl) view.replaceChildren(taskFormEl, boardEl);
    const tasks = (await api("GET", "/tasks")).tasks;
    boardEl.replaceChildren(h("div", { class: "grid" }, TASK_COLS.map((col) => {
      const items = tasks.filter((t) => t.status === col[0]);
      return h("section", null, h("h2", null, col[1] + " (" + items.length + ")"), h("div", { class: "list" }, items.map(taskCard)));
    })));
  };

  const SETTINGS_NOTE = "A value saved here wins over the .env file. Saved keys are encrypted and can never be read back.";
  const sourceTag = (it) => h("span", { class: "tag" }, it.source === "dashboard" ? "set here" : (it.source === "env" ? "from .env" : "default"));
  const llmFields = (p) => {
    const up = p.toUpperCase();
    if (p === "gemini") return [["GEMINI_CHAT_MODEL", "Model", "chat model name"], ["GEMINI_API_KEY", "API key", ""]];
    if (p === "anthropic") return [["ANTHROPIC_MODEL", "Model", "chat model name"], ["ANTHROPIC_API_KEY", "API key", ""]];
    const rows = [[up + "_MODEL", "Model", "chat model name"]];
    if (p !== "ollama") rows.push([up + "_API_KEY", "API key", ""]);
    rows.push([up + "_BASE_URL", p === "ollama" ? "Address" : "Address (optional)", "include the http prefix, e.g. host.docker.internal:11434/v1"]);
    return rows;
  };
  const embFields = (p) => {
    if (p === "gemini") return [["GEMINI_EMBEDDING_MODEL", "Model", "embedding model name"], ["GEMINI_API_KEY", "API key", ""]];
    const up = p.toUpperCase();
    const rows = [[up + "_EMBEDDING_MODEL", "Model", p === "ollama" ? "nomic-embed-text" : "embedding model name"]];
    if (p !== "ollama") rows.push([up + "_API_KEY", "API key", ""]);
    rows.push([up + "_BASE_URL", p === "ollama" ? "Address" : "Address (optional)", "include the http prefix, e.g. host.docker.internal:11434/v1"]);
    return rows;
  };
  let settingsEl = null;
  const buildSettings = (data, note) => {
    const items = {};
    data.settings.forEach((s) => { items[s.name] = s; });
    const stores = { llm: {}, emb: {}, common: {} };
    const msg = h("p", { class: "sub" }, note || "");
    const reload = async (text) => {
      try { const d = await api("GET", "/settings"); settingsEl = buildSettings(d, text); view.replaceChildren(settingsEl); }
      catch (e) { if (String(e.message) !== "unauthorized") msg.textContent = "Failed: " + clip(e.message, 120); }
    };
    const save = async (values, okText) => {
      if (!Object.keys(values).length) { msg.textContent = "Nothing to save."; return; }
      msg.textContent = "Saving...";
      try {
        const r = await api("PUT", "/settings", { values: values });
        let text = okText || "Saved.";
        const bad = (r.vector_status || []).filter((v) => v.status === "mismatch");
        if (bad.length) text += " Warning: stored documents use a different vector size, so nothing was resized. Re-ingest after clearing them, or switch back.";
        reload(text);
      } catch (e) { msg.textContent = "Failed: " + clip(e.message, 160); }
    };
    const field = (store, name, label, hint) => {
      const it = items[name];
      if (!it) return null;
      const el = h("input", { type: it.secret ? "password" : "text", placeholder: it.secret && it.is_set ? "leave blank to keep" : (hint || ""), autocomplete: "off", maxlength: 512 });
      if (!it.secret) el.value = it.value || "";
      store[name] = { el: el, secret: it.secret, orig: it.secret ? "" : (it.value || "") };
      let tag;
      if (it.secret) tag = h("span", { class: "tag " + (it.is_set ? "ok" : "") }, it.is_set ? (it.source === "dashboard" ? "saved, hidden" : "set in .env, hidden") : "not set");
      else tag = sourceTag(it);
      const rm = it.secret && it.source === "dashboard"
        ? h("button", { type: "button", class: "ghost", on: { click: () => save({ [name]: null }, "Removed.") } }, "Remove") : null;
      return h("div", { class: "row" }, h("label", { class: "sub" }, label), el, tag, rm);
    };
    const select = (list, current) => {
      const s = h("select", null, list.map((p) => h("option", { value: p }, p)));
      if (list.includes(current)) s.value = current;
      return s;
    };
    const origLlm = ((items.LLM_PROVIDER && items.LLM_PROVIDER.value) || "gemini").toLowerCase();
    const origEmb = ((items.EMBEDDING_PROVIDER && items.EMBEDDING_PROVIDER.value) || "gemini").toLowerCase();
    const llmSel = select(data.providers.llm, origLlm);
    const embSel = select(data.providers.embedding, origEmb);
    const llmBox = h("div", { class: "list" });
    const embBox = h("div", { class: "list" });
    const draw = (box, store, rows) => {
      Object.keys(store).forEach((k) => { delete store[k]; });
      box.replaceChildren(...rows.map((r) => field(store, r[0], r[1], r[2])).filter(Boolean));
    };
    const drawLlm = () => draw(llmBox, stores.llm, llmFields(llmSel.value));
    const drawEmb = () => draw(embBox, stores.emb, embFields(embSel.value));
    llmSel.addEventListener("change", drawLlm);
    embSel.addEventListener("change", drawEmb);
    drawLlm();
    drawEmb();
    const fallbackRow = field(stores.common, "LLM_FALLBACK_PROVIDERS", "Fallbacks", "comma separated, e.g. groq,gemini");
    const dimsRow = field(stores.common, "EMBEDDING_DIMENSIONS", "Vector size", "must match the model, e.g. 768 or 3072");
    const collect = () => {
      const out = {};
      Object.values(stores).forEach((store) => Object.keys(store).forEach((n) => {
        const f = store[n];
        const v = f.el.value.trim();
        if (f.secret) { if (v) out[n] = v; } else if (v !== f.orig) out[n] = v;
      }));
      if (llmSel.value !== origLlm) out.LLM_PROVIDER = llmSel.value;
      if (embSel.value !== origEmb) out.EMBEDDING_PROVIDER = embSel.value;
      return out;
    };
    const testBtn = (label, path) => h("button", { type: "button", on: { click: async () => {
      msg.textContent = "Testing the saved settings (save first if you changed something)...";
      try {
        const r = await api("POST", path);
        msg.textContent = r.ok ? ("Works: " + r.provider + " / " + r.model + (r.dimensions ? " (" + r.dimensions + " dims)" : "")) : ("Problem: " + (r.hint || r.error));
      } catch (e) { msg.textContent = "Failed: " + clip(e.message, 120); }
    } } }, label);
    return h("div", { class: "list" },
      h("p", { class: "sub" }, SETTINGS_NOTE),
      data.encryption_ready ? null : h("p", { class: "err" }, "Keys cannot be saved here: ADDON_ENCRYPTION_KEY is not set on the server."),
      h("section", { class: "dept" }, h("h2", null, "Chat AI"),
        h("div", { class: "row" }, h("label", { class: "sub" }, "Provider"), llmSel),
        llmBox, fallbackRow, h("div", { class: "row" }, testBtn("Test chat AI", "/settings/test/llm"))),
      h("section", { class: "dept" }, h("h2", null, "Embeddings (document search)"),
        h("p", { class: "sub" }, "Changing the embedding model after you have added documents means re-adding them."),
        h("div", { class: "row" }, h("label", { class: "sub" }, "Provider"), embSel),
        embBox, dimsRow, h("div", { class: "row" }, testBtn("Test embeddings", "/settings/test/embedding"))),
      h("div", { class: "row" }, h("button", { type: "button", class: "ok", on: { click: () => save(collect()) } }, "Save changes"), msg));
  };
  const refreshSettings = async () => {
    if (settingsEl && view.firstChild === settingsEl) return;
    settingsEl = buildSettings(await api("GET", "/settings"), "");
    view.replaceChildren(settingsEl);
  };

  const SETUP_TAG = { ok: "ok", todo: "bad", warn: "warn", info: "" };
  const SETUP_WORD = { ok: "done", todo: "needs setup", warn: "check this", info: "info" };
  const renderSetup = (s) => h("div", { class: "list" },
    h("div", { class: "card" + (s.ready ? "" : " warn") },
      h("div", { class: "lab" }, "Setup"),
      h("div", { class: "big" }, s.ready ? "Ready" : "Almost there"),
      h("div", { class: "sub" }, s.summary)),
    s.items.map((it) => h("article", { class: "item" },
      h("div", { class: "row" },
        h("strong", null, it.title),
        h("span", { class: "tag " + (SETUP_TAG[it.state] || "") }, SETUP_WORD[it.state] || it.state),
        it.required ? h("span", { class: "tag" }, "required") : null),
      h("div", { class: "sub" }, it.detail),
      it.action ? h("div", { class: "sub" }, "What to do: " + it.action) : null,
      it.fix === "settings" ? h("div", { class: "row" }, h("button", { type: "button", on: { click: () => { tab = "settings"; armed = false; refresh(); } } }, "Open Settings")) : null)));

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
      else if (tab === "employees") content = renderOrg(await api("GET", "/org"));
      else if (tab === "tasks") { await refreshTasks(); content = null; }
      else if (tab === "settings") { await refreshSettings(); content = null; }
      else if (tab === "setup") content = renderSetup(await api("GET", "/setup/status"));
      else content = renderLog((await api("GET", "/autonomy/log?limit=60")).log);
      if (content) view.replaceChildren(content);
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
    try { const s = await api("GET", "/setup/status"); if (!s.ready) tab = "setup"; } catch (e) { /* the checklist is optional */ }
    await refresh();
    if (timer) clearInterval(timer);
    timer = setInterval(refresh, 10000);
  };

  if (key) start(); else showLogin("");
})();
