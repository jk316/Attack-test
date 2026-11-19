// ── WebSocket Connection ──────────────────────────────────────
const clientId = crypto.randomUUID().slice(0, 8);
const protocol = location.protocol === "https:" ? "wss:" : "ws:";

const messagesEl = document.getElementById("messages");
const wsStatusEl = document.getElementById("wsStatus");
const threadIdEl = document.getElementById("threadId");
const expStatusEl = document.getElementById("expStatus");

// ws 可变（自动重连复用同一 client_id，断线不丢会话所有权）
let ws = null;
let reconnectTried = false;

function createWebSocket() {
  const sock = new WebSocket(`${protocol}//${location.host}/ws/${clientId}`);

  sock.onopen = () => {
    wsStatusEl.textContent = "WS 已连接";
    wsStatusEl.className = "badge connected";
    addMessage("status", "WebSocket 已连接 (client_id: " + clientId + ")");
  };

  sock.onclose = () => {
    wsStatusEl.textContent = "WS 未连接";
    wsStatusEl.className = "badge disconnected";
    addMessage("status", "WebSocket 已断开");
    if (!reconnectTried) {
      reconnectTried = true;
      addMessage("status", "1 秒后自动重连一次（同一 client_id）…");
      setTimeout(() => { ws = createWebSocket(); }, 1000);
    } else {
      addMessage("error", "重连失败：请刷新页面重新连接（刷新后为新会话，实验不终止但需在新页面重新审批）");
    }
  };

  sock.onmessage = (event) => {
    const payload = JSON.parse(event.data);
    handleMessage(payload.type, payload.data);
  };

  return sock;
}

ws = createWebSocket();

// ── Message Dispatcher ────────────────────────────────────────
function handleMessage(type, data) {
  switch (type) {
    case "status":
      if (data.thread_id) threadIdEl.textContent = "Thread: " + data.thread_id;
      break;

    case "messages":
      if (data && Array.isArray(data)) {
        data.forEach(m => addAIMessage(m));
      }
      break;

    case "tool_result":
      addToolResult(data);
      break;

    case "hitl_request":
      showHitlModal(data);
      break;

    case "hitl_response":
      if (data && data.approved) {
        addMessage("status", "HITL 审批通过");
      } else {
        addMessage("status", "HITL 审批拒绝");
      }
      break;

    case "experiment_done":
      if (data && data.summary) {
        addMessage("status", "实验完成");
        addSummary(data.summary);  // 摘要渲染（≤2000 字符，文本节点防注入）
      } else {
        addMessage("status", (data && data.message) || "实验已结束");
      }
      expStatusEl.textContent = "已完成";
      setRunning(false);
      break;

    case "error":
      if (data && data.message && data.message.indexOf("已在运行") !== -1) {
        // 启动被拒（FR-009 前端语义）：回滚运行态为就绪
        setRunning(false);
      }
      addMessage("error", "错误: " + (data.message || "未知错误"));
      break;
  }
}

// ── 默认值单一来源（007-G4/宪法六）─────────────────────────────
// 页面加载时拉取 /api/experiment/defaults 填充表单初值
async function loadDefaults() {
  try {
    const resp = await fetch("/api/experiment/defaults");
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    const defaults = await resp.json();
    document.getElementById("targetIp").value = defaults.target_ip || "";
    document.getElementById("maxIters").value = defaults.max_iters || "";
    document.getElementById("noImproveLimit").value = defaults.no_improve_limit || "";
    document.getElementById("targetIp").placeholder = defaults.target_ip || "目标 IP";
  } catch (e) {
    addMessage("error", "默认值加载失败: " + e.message);
  }
}
loadDefaults();

// ── Add Messages to Panel ─────────────────────────────────────
function addMessage(cls, text) {
  const div = document.createElement("div");
  div.className = `msg msg-${cls}`;
  div.textContent = text;
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function addAIMessage(msg) {
  const div = document.createElement("div");
  div.className = "msg msg-ai";

  let html = "";
  if (msg.tool_calls && msg.tool_calls.length > 0) {
    // Show tool calls as badges
    const badges = msg.tool_calls.map(tc =>
      `<span class="tc-badge">${tc.name}(${JSON.stringify(tc.args).slice(0, 60)})</span>`
    ).join(" ");
    html += badges + " ";
  }
  if (msg.content) {
    html += escapeHtml(msg.content.slice(0, 1000));
  }

  div.innerHTML = html;
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function addToolResult(msg) {
  const div = document.createElement("div");
  div.className = "msg msg-tool";
  const content = msg.content || "(no output)";
  div.textContent = "Tool result: " + content.slice(0, 300);
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  updateStatsFromToolResult(msg);  // 统计卡数据源（G5）
}

// ── 统计卡数据源（G5）─────────────────────────────────────────
// v1：从 tool_result 解析（流量轮次 / 最佳 RTT / 最近 RTT）；
// 解析不到时明确显示「暂未采集」。
let statsBestRtt = null;
let statsTrafficRounds = 0;

function resetStats() {
  statsBestRtt = null;
  statsTrafficRounds = 0;
  document.getElementById("statIter").textContent = "暂未采集";
  document.getElementById("statBestRtt").textContent = "暂未采集";
  document.getElementById("statLastRtt").textContent = "暂未采集";
}

function updateStatsFromToolResult(msg) {
  let data = msg.content;
  if (typeof data === "string") {
    try { data = JSON.parse(data); } catch (e) { return; }
  }
  if (!data || typeof data !== "object") return;
  const isTraffic = data.rtt_during !== undefined || data.packets_sent !== undefined;
  if (isTraffic) {
    statsTrafficRounds += 1;
    document.getElementById("statIter").textContent = String(statsTrafficRounds);
  }
  const rtt = data.rtt_during;
  if (rtt && typeof rtt.avg_rtt_ms === "number") {
    const avg = rtt.avg_rtt_ms;
    document.getElementById("statLastRtt").textContent = avg.toFixed(1) + " ms";
    if (statsBestRtt === null || avg > statsBestRtt) {
      statsBestRtt = avg;
      document.getElementById("statBestRtt").textContent = statsBestRtt.toFixed(1) + " ms";
    }
  }
}

function addSummary(text) {
  const div = document.createElement("div");
  div.className = "msg msg-summary";
  div.textContent = String(text).slice(0, 2000);
  messagesEl.appendChild(div);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

function escapeHtml(str) {
  const d = document.createElement("div");
  d.textContent = str;
  return d.innerHTML;
}

// ── HITL Modal ────────────────────────────────────────────────
const hitlModal = document.getElementById("hitlModal");
const hitlBody = document.getElementById("hitlBody");
let _hitlResolve = null;

function showHitlModal(data) {
  // 审批弹窗：message + scope（008 统一结构，可选）+ params 明细；
  // 全部走 textContent（天然 HTML 转义，防注入）
  let text = data.message || "";
  if (data.scope) {
    text += "\n\n审批范围:\n" + JSON.stringify(data.scope, null, 2);
  }
  if (data.params) {
    text += "\n\n参数明细:\n" + JSON.stringify(data.params, null, 2);
  }
  hitlBody.textContent = text;
  hitlModal.style.display = "flex";
  addMessage("hitl", "HITL 审批请求: " + (data.params ? JSON.stringify(data.params) : ""));

  return new Promise((resolve) => {
    _hitlResolve = resolve;
  });
}

document.getElementById("hitlApprove").onclick = () => {
  hitlModal.style.display = "none";
  ws.send(JSON.stringify({ type: "hitl_response", data: { approved: true } }));
  if (_hitlResolve) _hitlResolve(true);
};

document.getElementById("hitlReject").onclick = () => {
  hitlModal.style.display = "none";
  ws.send(JSON.stringify({ type: "hitl_response", data: { approved: false } }));
  if (_hitlResolve) _hitlResolve(false);
};

// ── PCAP Upload ───────────────────────────────────────────────
const uploadBtn = document.getElementById("uploadBtn");
const pcapFileInput = document.getElementById("pcapFile");
const pcapPathInput = document.getElementById("pcapPath");

uploadBtn.onclick = () => pcapFileInput.click();

pcapFileInput.onchange = async () => {
  const file = pcapFileInput.files[0];
  if (!file) return;

  uploadBtn.textContent = "上传中...";
  uploadBtn.disabled = true;

  const formData = new FormData();
  formData.append("file", file);

  try {
    const resp = await fetch("/api/upload/pcap", { method: "POST", body: formData });
    const result = await resp.json();
    if (result.success) {
      pcapPathInput.value = result.file_path;
      addMessage("status", `PCAP 上传成功: ${result.file_name} (${result.size_bytes} bytes)`);
    } else {
      addMessage("error", "PCAP 上传失败: " + result.error);
    }
  } catch (e) {
    addMessage("error", "PCAP 上传出错: " + e.message);
  } finally {
    uploadBtn.textContent = "上传";
    uploadBtn.disabled = false;
  }
};

// ── Start / Stop ──────────────────────────────────────────────
const startBtn = document.getElementById("startBtn");
const stopBtn = document.getElementById("stopBtn");

function setRunning(running) {
  startBtn.disabled = running;
  stopBtn.disabled = !running;
  expStatusEl.textContent = running ? "运行中" : "就绪";
}

startBtn.onclick = () => {
  if (ws.readyState !== WebSocket.OPEN) {
    addMessage("error", "WebSocket 未连接");
    return;
  }

  const params = {
    target_ip: document.getElementById("targetIp").value.trim() || "100.1.11.20",
    max_iters: parseInt(document.getElementById("maxIters").value) || 20,
    no_improve_limit: parseInt(document.getElementById("noImproveLimit").value) || 5,
    pcap_path: document.getElementById("pcapPath").value.trim() || "",
    log_path: "data/experiment.jsonl",
  };

  ws.send(JSON.stringify({ type: "start_experiment", data: params }));
  setRunning(true);
  resetStats();
  addMessage("status", "实验已启动: " + JSON.stringify(params));
};

stopBtn.onclick = () => {
  ws.send(JSON.stringify({ type: "stop_experiment" }));
  addMessage("status", "已发送停止请求");
  setRunning(false);
};
