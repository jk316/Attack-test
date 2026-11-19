"""ExperimentManager — async bridge between LangGraph agent and WebSocket frontend.

Replaces the synchronous CLI loop in main.py with an async, WebSocket-driven
architecture that supports:
- Real-time message delivery to the frontend via WebSocket
- HITL approval flow via asyncio.Queue (no more blocking input())
- PCAP profile result forwarding
- Experiment lifecycle management (start/stop)

007-2 决议（单客户端会话模型）: 由进程级单例重构为 per-client_id 会话注册表——
每个 client_id 一个 ExperimentSession（实验运行 / 审批队列 / 所有者），
审批与停止只接受会话所有者（发起实验的 client_id）的操作；同一会话内
同一时刻至多一个实验（FR-009 按会话粒度）。

R7（003-T018 遗补）: 实验结束路径（finally 与主动 stop）调用
``get_ping_monitor().stop()``，与 src/main.py finally 一致——Web 实验结束
无残留探测进程（FR-016/G-003）。

R8（004-T017 遗补）: 上传画像后走同一 ``profile_to_params`` 映射路径注入
会话上下文（user message 种子行），与 CLI ``_apply_profile_seeds`` 一致。
"""
import asyncio
import json
import logging
from pathlib import Path
from uuid import uuid4

from langgraph.types import Command

from src.agent.graph import build_graph
from src.tools.ping_monitor import get_ping_monitor

logger = logging.getLogger("experiment")
logger.setLevel(logging.DEBUG)

# ── Message protocol helpers ────────────────────────────────────

def _msg_to_dict(msg) -> dict:
    """Convert a LangChain message to a JSON-safe dict for the frontend."""
    tc_list = getattr(msg, "tool_calls", None) or []
    tool_calls = [
        {"name": tc.get("name", "?"), "args": tc.get("args", {})}
        for tc in tc_list
    ] if tc_list else None

    return {
        "role": getattr(msg, "type", "unknown"),
        "content": getattr(msg, "content", ""),
        "tool_calls": tool_calls,
    }


def load_experiment_defaults() -> dict:
    """读取 src/config/experiment.json（配置单一来源，宪法六；007-G4/R8 共用）。

    读取失败返回空 dict（调用方逐字段兜底）。
    """
    config_path = (
        Path(__file__).resolve().parent.parent / "src" / "config" / "experiment.json"
    )
    try:
        with open(config_path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


class ExperimentSession:
    """One experiment run bound to an owner client_id (007-2).

    Holds the experiment's graph config, approval queue, stop flag and the
    WebSocket channel.  Approval decisions are consumed exactly once per
    HITL request (duplicate decisions are ignored — no pre-approval path).
    """

    def __init__(self, owner_client_id: str, graph, on_end=None):
        self.owner_client_id = owner_client_id
        self._graph = graph
        self._running = False
        self._stop_requested = False
        self._config: dict | None = None
        self._hitl_queue: asyncio.Queue = asyncio.Queue()
        self._hitl_pending = False  # True while a hitl_request awaits its single decision
        self._ws = None
        self._connected = False  # 007 FR-020：通道状态（断线不终止实验）
        self._on_end = on_end  # manager-level cleanup callback (R7)

    @property
    def running(self) -> bool:
        return self._running

    @property
    def connected(self) -> bool:
        return self._connected

    def rebind(self, websocket) -> None:
        """007 FR-020：同一 client_id 重连时把会话绑定到新通道。"""
        self._ws = websocket
        self._connected = True

    def mark_disconnected(self) -> None:
        """007 FR-020：断线标记（实验本身不因断线停止）。"""
        self._connected = False
        self._ws = None

    async def _safe_send(self, data: dict) -> bool:
        """向通道推送；断线/推送失败时静默降级，不中断实验。"""
        if not self._connected or self._ws is None:
            return False
        try:
            await self._ws.send_json(data)
            return True
        except Exception:
            self._connected = False
            self._ws = None
            return False

    async def start(self, params: dict, websocket) -> None:
        """Start an experiment, pushing messages to the given WebSocket."""
        if self._running:
            # 启动前的拒绝路径直接发往发起方通道（尚未绑定 _ws）
            await websocket.send_json({
                "type": "error",
                "data": {"message": "实验已在运行中，请先停止当前实验"},
            })
            return

        target_ip = params.get("target_ip", "") or load_experiment_defaults().get(
            "target_ip", "100.1.11.20")
        pcap_path = params.get("pcap_path", "")
        log_path = params.get("log_path", "data/experiment.jsonl")
        max_iters = params.get("max_iters", load_experiment_defaults().get("max_iters", 20))
        no_improve_limit = params.get("no_improve_limit",
                                      load_experiment_defaults().get("no_improve_limit", 5))

        # data-model「实验运行」约束字段：max_iters/no_improve_limit 必须 ≥1
        for name, value in (("max_iters", max_iters), ("no_improve_limit", no_improve_limit)):
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                await websocket.send_json({
                    "type": "error",
                    "data": {"message": f"{name} 必须为 ≥1 的整数（收到 {value!r}）"},
                })
                return

        self._running = True
        self._stop_requested = False
        self._hitl_queue = asyncio.Queue()
        self._hitl_pending = False
        self._ws = websocket
        self._connected = True

        thread_id = str(uuid4())[:8]
        self._config = {"configurable": {"thread_id": thread_id}}

        await self._safe_send({
            "type": "status",
            "data": {"status": "starting", "thread_id": thread_id},
        })

        pcap_line = (
            f"- PCAP文件路径: {pcap_path}\n"
            if pcap_path
            else "- PCAP文件路径: 无（使用默认初始参数）\n"
        )
        # R8（004-T017）：上传画像后走同一 profile_to_params 映射路径注入会话上下文
        seed_line = ""
        if pcap_path:
            try:
                from src.tools.pcap_profile_tool import pcap_profile_tool
                from src.tools.profile_to_params import profile_to_params

                profile = pcap_profile_tool(pcap_path=pcap_path)
                attack = load_experiment_defaults().get("attack", {}) or {}
                mapped = profile_to_params(profile, defaults={
                    "dst_port": 8080,
                    "packet_size": attack.get("packet_size", 64),
                    "pps": attack.get("pps", 100),
                    "flow_count": attack.get("flow_count", 1),
                    "duration_s": attack.get("duration_s", 10),
                })
                seed_line = (
                    f"- 画像映射初始参数: dst_port={mapped['dst_port']}, "
                    f"packet_size={mapped['packet_size']}, "
                    f"flow_count={mapped['flow_count']}, pps={mapped['pps']}\n"
                )
            except Exception as e:
                logger.warning("PCAP 画像分析失败，使用默认初始参数: %s", e)
                seed_line = f"- 画像分析失败（{e}），使用默认初始参数\n"

        user_message = (
            "请开始闭环网络实验：\n"
            f"- 目标IP: {target_ip}\n"
            f"- 最大迭代次数: {max_iters}\n"
            f"- 无改善停止轮数: {no_improve_limit}\n"
            f"- 日志文件路径: {log_path}\n"
            + pcap_line
            + seed_line
            + "\n请严格按照系统提示中的实验协议执行。"
            "如果提供了PCAP文件，先用 pcap_profile 工具分析流量特征。"
        )

        initial_state = {"messages": [{"role": "user", "content": user_message}]}

        logger.info("Starting experiment: thread=%s, target=%s", thread_id, target_ip)

        try:
            await self._run_loop(initial_state)
        except Exception as e:
            logger.exception("Experiment error")
            await self._safe_send({
                "type": "error",
                "data": {"message": str(e)},
            })
        finally:
            self._running = False
            # 终态推送须先于通道解绑（否则 _safe_send 会静默丢弃）
            await self._safe_send({
                "type": "experiment_done",
                "data": {"message": "实验已结束"},
            })
            self._ws = None
            self._connected = False
            self._stop_ping_monitor()  # R7：实验结束路径清理监控
            if self._on_end is not None:
                self._on_end()  # R7：manager 级清理守卫

    async def approve(self, approved: bool) -> str:
        """Signal HITL approval result into the experiment's queue.

        Returns "applied" when the decision was consumed for a pending
        request, "ignored" for duplicate decisions (each request consumes
        exactly one — no pre-approval path).
        """
        if not self._running or not self._hitl_pending:
            return "ignored"
        self._hitl_pending = False
        await self._hitl_queue.put(approved)
        return "applied"

    async def stop(self) -> None:
        """Request graceful stop of the current experiment.

        When the experiment is awaiting a HITL decision, the stop wins:
        a rejection value is injected to unblock the pending get().
        """
        self._stop_requested = True
        if self._hitl_pending:
            self._hitl_pending = False
            await self._hitl_queue.put(False)

    def _stop_ping_monitor(self) -> None:
        """R7：清理后台 ping 监控（幂等；与 src/main.py finally 一致）。"""
        try:
            monitor = get_ping_monitor()
            if monitor.is_running():
                logger.info("Cleaning up ping monitor...")
                monitor.stop()
        except Exception:
            pass

    # ── Internal ────────────────────────────────────────────────

    async def _run_loop(self, initial_state: dict) -> None:
        """Core loop: ainvoke → push messages → handle HITL → repeat.

        Matches the main.py pattern: each ainvoke runs atomically until the
        next interrupt() or graph completion. After each ainvoke we extract
        new messages and push them to the frontend.
        """
        graph = self._graph
        config = self._config
        ws = self._ws

        if self._hitl_queue is None:
            self._hitl_queue = asyncio.Queue()

        await graph.ainvoke(initial_state, config)
        await self._push_new_messages(0)

        while not self._stop_requested:
            gs = graph.get_state(config)
            if not gs or not gs.next:
                break

            # Graph paused (interrupt triggered) — extract info for display
            hitl_info = self._extract_hitl(gs) or {
                "message": "[HITL] 实验被中断，请确认是否继续",
                "params": {},
            }

            self._hitl_pending = True
            await self._safe_send({"type": "hitl_request", "data": hitl_info})

            approved = await self._hitl_queue.get()

            await self._safe_send({
                "type": "hitl_response",
                "data": {"approved": approved},
            })

            prev_count = len(gs.values.get("messages", [])) if gs.values else 0

            await graph.ainvoke(Command(resume=approved), config)

            await self._push_new_messages(prev_count)

        self._send_final_summary()

    def _send_final_summary(self):
        """Extract and push the final agent summary."""
        gs = self._graph.get_state(self._config)
        ws = self._ws
        if not gs or not gs.values or not ws:
            return
        messages = gs.values.get("messages", [])
        if messages:
            last_msg = messages[-1]
            summary = getattr(last_msg, "content", str(last_msg))
            if summary:
                asyncio.create_task(
                    self._safe_send({
                        "type": "experiment_done",
                        "data": {"summary": summary[:2000]},
                    })
                )

    async def _push_new_messages(self, since: int) -> None:
        """Send all messages after index `since` to the WebSocket frontend."""
        gs = self._graph.get_state(self._config)
        if not gs or not gs.values:
            return
        messages = gs.values.get("messages", [])
        new_msgs = messages[since:]
        for msg in new_msgs:
            msg_dict = _msg_to_dict(msg)
            if msg_dict["role"] == "tool":
                await self._safe_send({"type": "tool_result", "data": msg_dict})
            else:
                await self._safe_send({"type": "messages", "data": [msg_dict]})

    @staticmethod
    def _extract_hitl(gs) -> dict | None:
        """Extract HITL interrupt info from a StateSnapshot, if any."""
        tasks = getattr(gs, 'tasks', None) or []
        for task in tasks:
            interrupts = getattr(task, 'interrupts', None) or []
            for intr in interrupts:
                val = intr.value
                if isinstance(val, dict) and "message" in val:
                    return val
        return None


class ExperimentManager:
    """per-client_id 会话注册表（007-2 单客户端会话模型）。

    映射 client_id → ExperimentSession；同一 client_id 同一时刻至多一个
    运行中实验；审批与停止只接受会话所有者的操作。
    """

    def __init__(self):
        self._graph = build_graph()
        self._sessions: dict[str, ExperimentSession] = {}

    def _get_session(self, client_id: str) -> ExperimentSession:
        if client_id not in self._sessions:
            self._sessions[client_id] = ExperimentSession(
                client_id, self._graph, on_end=self._on_session_end,
            )
        return self._sessions[client_id]

    @property
    def running(self) -> bool:
        return any(s.running for s in self._sessions.values())

    def _on_session_end(self) -> None:
        """R7：会话结束回调——若无其他会话仍在运行，清理进程级 ping 监控。"""
        if any(s.running for s in self._sessions.values()):
            return
        try:
            monitor = get_ping_monitor()
            if monitor.is_running():
                logger.info("Cleaning up ping monitor (no running sessions)...")
                monitor.stop()
        except Exception:
            pass

    async def start(self, client_id: str, params: dict, websocket) -> None:
        session = self._get_session(client_id)
        await session.start(params, websocket)

    def bind_ws(self, client_id: str, websocket) -> None:
        """007 FR-020：同一 client_id 重连时把既有会话绑定到新通道。"""
        session = self._sessions.get(client_id)
        if session is not None:
            session.rebind(websocket)

    def mark_disconnected(self, client_id: str) -> None:
        """007 FR-020：断线标记会话断开（实验本身不因断线停止）。"""
        session = self._sessions.get(client_id)
        if session is not None:
            session.mark_disconnected()

    async def approve(self, client_id: str, approved: bool) -> str:
        """会话所有者校验（007-2/FR-013）。

        Returns "applied" / "ignored" / "not_owner"——非发起实验的
        client_id 的决定被拒绝且不改变实验状态。
        """
        session = self._sessions.get(client_id)
        if session is None or not session.running:
            return "not_owner"
        return await session.approve(approved)

    async def stop(self, client_id: str) -> str:
        """会话所有者校验后的优雅停止请求。"""
        session = self._sessions.get(client_id)
        if session is None or not session.running:
            return "not_owner"
        await session.stop()
        return "applied"

    async def stop_all(self) -> None:
        """通道外停止（REST /api/experiment/stop）：停止所有运行中会话。"""
        for session in list(self._sessions.values()):
            if session.running:
                await session.stop()
