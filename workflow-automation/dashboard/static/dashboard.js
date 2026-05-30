/* WA3 At-Desk Dashboard — vanilla JS frontend.
 *
 * Wires the four panels to the FastAPI server endpoints. Single
 * WebSocket for live events; HTTP polling for state / outbox / quota
 * (low-frequency, ~3-5s). Keep this dependency-free; CDN is allowed
 * per spec but we don't need it for this v1.
 */

(function () {
  "use strict";

  const EVENT_BUFFER_CAP_UI = 250;
  const STATE_POLL_MS = 5000;
  const OUTBOX_POLL_MS = 3000;
  const QUOTA_POLL_MS = 5000;

  // ---------- Helpers ----------

  function $(id) { return document.getElementById(id); }

  function escapeHtml(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function fmtTime(ts) {
    if (!ts) return "";
    try {
      const d = new Date(ts);
      const hh = String(d.getHours()).padStart(2, "0");
      const mm = String(d.getMinutes()).padStart(2, "0");
      const ss = String(d.getSeconds()).padStart(2, "0");
      return `${hh}:${mm}:${ss}`;
    } catch {
      return ts;
    }
  }

  function fmtNum(n) {
    if (n == null) return "—";
    if (n < 1000) return String(n);
    if (n < 1_000_000) return `${(n / 1000).toFixed(1)}k`;
    return `${(n / 1_000_000).toFixed(2)}M`;
  }

  function setConn(state, text) {
    const dot = $("conn-dot");
    const t = $("conn-text");
    dot.className = "dot dot-" + state;
    t.textContent = text;
  }

  // ---------- Activity stream (B3) ----------

  const events = [];     // most recent at the end
  let totalEventsSeen = 0;

  function shouldShow(ev) {
    const name = (ev.hook_event_name || "").toLowerCase();
    if (name === "pretooluse") return $("filter-pretooluse").checked;
    if (name === "posttooluse") return $("filter-posttooluse").checked;
    return $("filter-other").checked;
  }

  function renderEvents() {
    const ul = $("event-list");
    if (events.length === 0) {
      ul.innerHTML = '<li class="event-empty">No events yet. Configure Claude Code hooks per the README to stream events here.</li>';
      $("event-count").textContent = "0";
      return;
    }
    $("event-count").textContent = String(totalEventsSeen);
    // Render visible-only (filtered). Newest first.
    const visible = events.filter(shouldShow).slice().reverse();
    if (visible.length === 0) {
      ul.innerHTML = '<li class="event-empty">All events filtered out.</li>';
      return;
    }
    ul.innerHTML = visible.map(renderEventHTML).join("");
  }

  function renderEventHTML(ev) {
    const tag = (ev.hook_event_name || "").toLowerCase();
    const tagClass = tag.indexOf("pre") === 0 ? "pre" : tag.indexOf("post") === 0 ? "post" : "";
    const tool = ev.tool_name ? `<span class="event-tool">${escapeHtml(ev.tool_name)}</span>` : "";
    const duration = ev.duration_ms != null ? `<span class="event-duration">${ev.duration_ms} ms</span>` : "";
    let row2 = "";
    if (ev.tool_input) {
      const compact = JSON.stringify(ev.tool_input);
      row2 = `<div class="event-row2">→ ${escapeHtml(compact)}</div>`;
    }
    if (ev.tool_response_excerpt) {
      row2 += `<div class="event-row2">← ${escapeHtml(ev.tool_response_excerpt)}</div>`;
    }
    const detail = JSON.stringify(ev, null, 2);
    return `
      <li class="event-item" data-id="${ev.id}">
        <div class="event-item-row1">
          <span class="event-time">${escapeHtml(fmtTime(ev.ts))}</span>
          <span class="event-tag ${tagClass}">${escapeHtml(ev.hook_event_name || "?")}</span>
          ${tool}
          ${duration}
        </div>
        ${row2}
        <pre class="event-detail">${escapeHtml(detail)}</pre>
      </li>`;
  }

  function pushEvent(ev) {
    events.push(ev);
    totalEventsSeen += 1;
    if (events.length > EVENT_BUFFER_CAP_UI) events.shift();
    renderEvents();
  }

  // Click an event row to toggle the JSON detail.
  document.addEventListener("click", (e) => {
    const li = e.target.closest && e.target.closest(".event-item");
    if (li) li.classList.toggle("open");
  });
  ["filter-pretooluse", "filter-posttooluse", "filter-other"].forEach((id) => {
    $(id).addEventListener("change", renderEvents);
  });
  $("clear-events").addEventListener("click", () => {
    events.length = 0;
    totalEventsSeen = 0;
    renderEvents();
  });

  // ---------- WebSocket connection ----------

  let ws = null;
  let wsReconnectMs = 1000;

  function connectWs() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const url = `${proto}://${location.host}/ws/events`;
    setConn("warn", "connecting...");
    ws = new WebSocket(url);
    ws.onopen = () => {
      setConn("ok", "live");
      wsReconnectMs = 1000;
    };
    ws.onmessage = (e) => {
      let msg;
      try { msg = JSON.parse(e.data); } catch { return; }
      if (msg.type === "backfill" && Array.isArray(msg.events)) {
        msg.events.forEach((ev) => {
          events.push(ev);
          totalEventsSeen += 1;
        });
        renderEvents();
      } else if (msg.type === "event" && msg.event) {
        pushEvent(msg.event);
      }
    };
    ws.onclose = () => {
      setConn("bad", `disconnected (retry in ${Math.round(wsReconnectMs / 1000)}s)`);
      setTimeout(connectWs, wsReconnectMs);
      wsReconnectMs = Math.min(wsReconnectMs * 2, 30000);
    };
    ws.onerror = () => {
      // onclose will fire too.
    };
  }
  connectWs();

  // ---------- State panel (B2) ----------

  async function refreshState() {
    try {
      const r = await fetch("/api/state");
      const data = await r.json();
      $("state-body").innerHTML = renderStateHTML(data);
    } catch (e) {
      $("state-body").innerHTML = `<p class="state-empty">State fetch failed: ${escapeHtml(String(e))}</p>`;
    }
  }

  function renderStateHTML(s) {
    if (s._state === "empty") {
      return `<p class="state-empty">No <code>planner_state.json</code> at <code>${escapeHtml(s._state_dir || "")}</code>. Bootstrap one with the WA1 <code>planner_state</code> library to populate this panel.</p>`;
    }
    if (s._state === "error") {
      return `<p class="state-empty">State error: ${escapeHtml(s._error || "")}</p>`;
    }
    const out = [];
    if (s.project) {
      out.push(`<h3>Project</h3><ul>`);
      if (s.project.name) out.push(`<li><strong>${escapeHtml(s.project.name)}</strong></li>`);
      if (s.project.current_pointer) out.push(`<li>${escapeHtml(s.project.current_pointer)}</li>`);
      out.push("</ul>");
    }
    const ls = s.loop_state || {};
    out.push("<h3>Loop state</h3><ul>");
    if (ls.current_pass) {
      out.push(`<li>Pass: <code>${escapeHtml(ls.current_pass)}</code> (status <code>${escapeHtml(ls.current_pass_status || "")}</code>)</li>`);
    } else {
      out.push(`<li>No pass in flight (status <code>${escapeHtml(ls.current_pass_status || "idle")}</code>)</li>`);
    }
    if (Array.isArray(ls.pending) && ls.pending.length) {
      out.push("<li>Pending:<ul>");
      ls.pending.forEach((x) => out.push(`<li>${escapeHtml(x)}</li>`));
      out.push("</ul></li>");
    } else {
      out.push("<li>Pending: (none)</li>");
    }
    if (Array.isArray(ls.blocked) && ls.blocked.length) {
      out.push("<li>Blocked:<ul>");
      ls.blocked.forEach((b) => {
        const item = escapeHtml(b.item || "(unspecified)");
        const reason = b.reason ? ` — <em>${escapeHtml(b.reason)}</em>` : "";
        out.push(`<li>${item}${reason}</li>`);
      });
      out.push("</ul></li>");
    } else {
      out.push("<li>Blocked: (none)</li>");
    }
    out.push("</ul>");
    if (ls.last_code_activity) {
      const lca = ls.last_code_activity;
      out.push("<h3>Last Code activity</h3>");
      out.push(`<p>${escapeHtml(lca.pass || "")} ${lca.result ? `(${escapeHtml(lca.result)})` : ""} ${lca.timestamp ? `at ${escapeHtml(lca.timestamp)}` : ""}</p>`);
      if (lca.summary) out.push(`<p class="muted">${escapeHtml(lca.summary)}</p>`);
    }
    if (Array.isArray(s.decisions) && s.decisions.length) {
      out.push("<h3>Recent locked decisions</h3>");
      const recent = s.decisions.slice(-6).reverse();
      recent.forEach((d) => {
        out.push(`<div class="decision"><div><strong>${escapeHtml(d.topic || "")}</strong> <span class="decision-meta">${escapeHtml(d.date || "")}</span></div><div>${escapeHtml(d.decision || "")}</div></div>`);
      });
      if (s.decisions.length > 6) {
        out.push(`<p class="muted">(plus ${s.decisions.length - 6} earlier; see <code>decisions[]</code>.)</p>`);
      }
    }
    if (s.working_context_digest && s.working_context_digest.trim()) {
      out.push("<h3>Working-context digest</h3>");
      out.push(`<p>${escapeHtml(s.working_context_digest)}</p>`);
    }
    return out.join("");
  }
  $("refresh-state").addEventListener("click", refreshState);
  refreshState();
  setInterval(refreshState, STATE_POLL_MS);

  // ---------- Chat (B4) ----------

  const seenRepliesBySpec = new Set();
  const chatHistory = [];

  function renderChat() {
    if (chatHistory.length === 0) {
      $("chat-history").innerHTML = '<p class="chat-empty">No chat history. Send a message to start the round-trip.</p>';
      return;
    }
    $("chat-history").innerHTML = chatHistory.map((m) => {
      const cls = m.direction === "out" ? "out" : "in";
      const meta = m.meta ? `<span class="meta">${escapeHtml(m.meta)}</span>` : "";
      return `<div class="chat-msg ${cls}">${escapeHtml(m.text)}${meta}</div>`;
    }).join("");
    const el = $("chat-history");
    el.scrollTop = el.scrollHeight;
  }

  async function sendChat(text) {
    chatHistory.push({ direction: "out", text, meta: `sent ${fmtTime(new Date().toISOString())}` });
    renderChat();
    try {
      const r = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      const data = await r.json();
      if (!data.ok) {
        chatHistory.push({ direction: "in", text: `Send failed: ${JSON.stringify(data)}`, meta: "" });
        renderChat();
      }
    } catch (e) {
      chatHistory.push({ direction: "in", text: `Send error: ${e}`, meta: "" });
      renderChat();
    }
  }

  $("chat-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = $("chat-input").value.trim();
    if (!text) return;
    $("chat-input").value = "";
    sendChat(text);
  });
  $("chat-input").addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      $("chat-form").dispatchEvent(new Event("submit", { cancelable: true }));
    }
  });

  async function pollOutbox() {
    try {
      const r = await fetch("/api/outbox");
      const data = await r.json();
      if (data && Array.isArray(data.replies)) {
        for (const reply of data.replies) {
          if (seenRepliesBySpec.has(reply.spec_id)) continue;
          seenRepliesBySpec.add(reply.spec_id);
          chatHistory.push({
            direction: "in",
            text: reply.body,
            meta: `from ${reply.spec_id}`,
          });
        }
        renderChat();
      }
    } catch {
      /* swallow; the next poll will retry */
    }
  }
  pollOutbox();
  setInterval(pollOutbox, OUTBOX_POLL_MS);

  // ---------- Quota panel (B5) ----------

  async function refreshQuota() {
    try {
      const r = await fetch("/api/quota");
      const data = await r.json();
      renderQuotaThrottle(data);
      renderQuotaSessions(data.sessions || {});
    } catch (e) {
      /* swallow */
    }
  }
  function renderQuotaThrottle(q) {
    const el = $("quota-throttle");
    if (q.throttled) {
      el.innerHTML = `<span class="throttle-state throttle-on">THROTTLED</span>${q.reset_at_text ? `<span class="throttle-reset">resets ${escapeHtml(q.reset_at_text)}</span>` : ""}`;
    } else {
      el.innerHTML = '<span class="throttle-state throttle-ok">OK — no throttle observed.</span>';
    }
  }
  function renderQuotaSessions(sessions) {
    const tbody = $("quota-sessions-body");
    const rows = Object.values(sessions);
    if (!rows.length) {
      tbody.innerHTML = '<tr><td colspan="5" class="muted">No sessions observed yet.</td></tr>';
      return;
    }
    rows.sort((a, b) => (b.last_observed_at || "").localeCompare(a.last_observed_at || ""));
    tbody.innerHTML = rows.map((s) => `
      <tr>
        <td class="session-id">${escapeHtml((s.session_id || "").slice(0, 12))}…</td>
        <td>${escapeHtml(s.model || "?")}</td>
        <td>${s.rounds || 0}</td>
        <td>${fmtNum(s.input_tokens || 0)} / ${fmtNum(s.output_tokens || 0)} / ${fmtNum(s.cache_read_input_tokens || 0)}</td>
        <td>${(s.total_cost_usd_telemetry || 0).toFixed(4)}</td>
      </tr>`).join("");
  }
  $("quota-clear").addEventListener("click", async () => {
    try {
      await fetch("/api/quota/clear", { method: "POST" });
      refreshQuota();
    } catch {}
  });
  refreshQuota();
  setInterval(refreshQuota, QUOTA_POLL_MS);
})();
