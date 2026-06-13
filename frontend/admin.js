const logFeed = document.getElementById("log-feed");
const wsStatus = document.getElementById("ws-status");
const statTotal = document.getElementById("stat-total");
const statApproved = document.getElementById("stat-approved");
const statDenied = document.getElementById("stat-denied");
const statAvgTools = document.getElementById("stat-avg-tools");

const stats = {
  totalRequests: 0,
  approved: 0,
  denied: 0,
  toolCallsBySession: {},
};

let ws = null;
let reconnectTimer = null;

function wsUrl() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}/ws/logs`;
}

function updateStats() {
  statTotal.textContent = stats.totalRequests;
  statApproved.textContent = stats.approved;
  statDenied.textContent = stats.denied;

  const sessions = Object.values(stats.toolCallsBySession);
  if (sessions.length === 0) {
    statAvgTools.textContent = "0";
  } else {
    const avg = sessions.reduce((a, b) => a + b, 0) / sessions.length;
    statAvgTools.textContent = avg.toFixed(1);
  }
}

function formatTime(iso) {
  try {
    return new Date(iso).toLocaleTimeString();
  } catch {
    return iso || "";
  }
}

function badgeClass(type) {
  const map = {
    thought: "badge-thought",
    tool_call: "badge-tool_call",
    tool_result: "badge-tool_result",
    decision: "badge-decision",
  };
  return map[type] || "badge-thought";
}

function badgeLabel(type) {
  const map = {
    thought: "THOUGHT",
    tool_call: "TOOL CALL",
    tool_result: "TOOL RESULT",
    decision: "DECISION",
  };
  return map[type] || type.toUpperCase();
}

function buildPayload(event) {
  const payload = { ...event };
  delete payload.type;
  delete payload.timestamp;
  delete payload.customer_id;
  return payload;
}

function renderLogCard(event) {
  const card = document.createElement("div");
  const isDecision = event.type === "decision";
  const decisionClass =
    isDecision && event.decision === "approve_refund"
      ? "approve"
      : isDecision && event.decision === "deny_refund"
        ? "deny"
        : "";

  card.className = `log-card type-${event.type}${decisionClass ? ` type-decision ${decisionClass}` : ""}`;

  const payload = buildPayload(event);
  const payloadJson = JSON.stringify(payload, null, 2);

  card.innerHTML = `
    <div class="log-header">
      <span class="type-badge ${badgeClass(event.type)}">${badgeLabel(event.type)}</span>
      <span class="log-timestamp">${formatTime(event.timestamp)}</span>
      ${event.customer_id ? `<span class="log-customer">${event.customer_id}</span>` : ""}
    </div>
    <div class="log-content">${summarizeEvent(event)}</div>
    <div class="log-payload">
      <button class="toggle-btn" aria-expanded="true">Collapse JSON</button>
      <pre>${escapeHtml(payloadJson)}</pre>
    </div>
  `;

  const toggleBtn = card.querySelector(".toggle-btn");
  const pre = card.querySelector("pre");
  toggleBtn.addEventListener("click", () => {
    const collapsed = pre.classList.toggle("collapsed");
    toggleBtn.textContent = collapsed ? "Expand JSON" : "Collapse JSON";
    toggleBtn.setAttribute("aria-expanded", String(!collapsed));
  });

  return card;
}

function summarizeEvent(event) {
  switch (event.type) {
    case "thought":
      return escapeHtml(String(event.content || "").slice(0, 300));
    case "tool_call":
      return `<strong>${escapeHtml(event.tool || "")}</strong> — ${escapeHtml(JSON.stringify(event.input || {}))}`;
    case "tool_result":
      return `<strong>${escapeHtml(event.tool || "")}</strong> returned result`;
    case "decision":
      return `<strong>${escapeHtml(event.decision || "unknown")}</strong>`;
    default:
      return escapeHtml(JSON.stringify(event));
  }
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function trackStats(event) {
  const cid = event.customer_id || "unknown";

  if (event.type === "tool_call") {
    if (!stats.toolCallsBySession[cid]) {
      stats.toolCallsBySession[cid] = 0;
    }
    stats.toolCallsBySession[cid]++;
  }

  if (event.type === "decision") {
    stats.totalRequests++;
    if (event.decision === "approve_refund") stats.approved++;
    else if (event.decision === "deny_refund") stats.denied++;
    delete stats.toolCallsBySession[cid];
  }

  updateStats();
}

function handleEvent(event) {
  if (logFeed.querySelector(".empty-feed")) {
    logFeed.innerHTML = "";
  }
  trackStats(event);
  const card = renderLogCard(event);
  logFeed.prepend(card);
}

function setWsStatus(connected) {
  wsStatus.textContent = connected ? "Connected" : "Disconnected";
  wsStatus.className = `ws-status ${connected ? "ws-connected" : "ws-disconnected"}`;
}

function connect() {
  if (ws && ws.readyState === WebSocket.OPEN) return;

  ws = new WebSocket(wsUrl());

  ws.onopen = () => {
    setWsStatus(true);
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  };

  ws.onmessage = (msg) => {
    try {
      const event = JSON.parse(msg.data);
      handleEvent(event);
    } catch {
      /* ignore malformed messages */
    }
  };

  ws.onclose = () => {
    setWsStatus(false);
    reconnectTimer = setTimeout(connect, 3000);
  };

  ws.onerror = () => {
    ws.close();
  };
}

if (logFeed.children.length === 0) {
  logFeed.innerHTML = '<p class="empty-feed">Waiting for agent activity…</p>';
}

connect();
