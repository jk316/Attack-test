// ── WebSocket Connection ──────────────────────────────────────
const clientId = crypto.randomUUID().slice(0, 8);
const protocol = location.protocol === "https:" ? "wss:" : "ws:";
const ws = new WebSocket(`${protocol}//${location.host}/ws/${clientId}`);

const messagesEl = document.getElementById("messages");
const wsStatusEl = document.getElementById("wsStatus");
const threadIdEl = document.getElementById("threadId");
const expStatusEl = document.getElementById("expStatus");

ws.onopen = () => {
  wsStatusEl.textContent = "WS 已连接";
  wsStatusEl.className = "badge connected";
  addMessage("status", "WebSocket 已连接");
};

ws.onclose = () => {
  wsStatusEl.textContent = "WS 未连接";
  wsStatusEl.className = "badge disconnected";
  addMessage("status", "WebSocket 已断开");
};

ws.onmessage = (event) => {
  const payload = JSON.parse(event.data);
  handleMessage(payload.type, payload.data);
};

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
      }
      expStatusEl.textContent = "已完成";
      setRunning(false);
      break;

    case "error":
      addMessage("error", "错误: " + (data.message || "未知错误"));
      break;
  }
}

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
  hitlBody.textContent = data.message + "\n\n" +
    JSON.stringify(data.params || {}, null, 2);
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
    target_ip: document.getElementById("targetIp").value.trim() || "10.99.80.160",
    max_iters: parseInt(document.getElementById("maxIters").value) || 20,
    no_improve_limit: parseInt(document.getElementById("noImproveLimit").value) || 5,
    pcap_path: document.getElementById("pcapPath").value.trim() || "",
    log_path: "data/experiment.jsonl",
  };

  ws.send(JSON.stringify({ type: "start_experiment", data: params }));
  setRunning(true);
  addMessage("status", "实验已启动: " + JSON.stringify(params));
};

stopBtn.onclick = () => {
  ws.send(JSON.stringify({ type: "stop_experiment" }));
  addMessage("status", "已发送停止请求");
  setRunning(false);
};
