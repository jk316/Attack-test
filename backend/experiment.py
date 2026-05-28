"""ExperimentManager — async bridge between LangGraph agent and WebSocket frontend.

Replaces the synchronous CLI loop in main.py with an async, WebSocket-driven
architecture that supports:
- Real-time message delivery to the frontend via WebSocket
- HITL approval flow via asyncio.Queue (no more blocking input())
- PCAP profile result forwarding
- Experiment lifecycle management (start/stop)
"""
import asyncio
import json
import logging
from pathlib import Path
from uuid import uuid4

from langgraph.types import Command

from src.agent.graph import build_graph

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


class ExperimentManager:
    """Manages the lifecycle of a single LangGraph experiment.

    One manager instance per process. Only one experiment can run at a time.
    """

    def __init__(self):
        self._graph = build_graph()
        self._running = False
        self._stop_requested = False
        self._config: dict | None = None
        self._hitl_queue: asyncio.Queue | None = None
        self._ws = None

    @property
    def running(self) -> bool:
        return self._running

    async def start(self, params: dict, websocket) -> None:
        """Start an experiment, pushing messages to the given WebSocket."""
        if self._running:
            await websocket.send_json({
                "type": "error",
                "data": {"message": "实验已在运行中，请先停止当前实验"},
            })
            return

        self._running = True
        self._stop_requested = False
        self._hitl_queue = asyncio.Queue()
        self._ws = websocket

        thread_id = str(uuid4())[:8]
        self._config = {"configurable": {"thread_id": thread_id}}

        target_ip = params.get("target_ip", "10.99.80.160")
        pcap_path = params.get("pcap_path", "")
        log_path = params.get("log_path", "data/experiment.jsonl")
        max_iters = params.get("max_iters", 20)
        no_improve_limit = params.get("no_improve_limit", 5)

        await websocket.send_json({
            "type": "status",
            "data": {"status": "starting", "thread_id": thread_id},
        })

        pcap_line = (
            f"- PCAP文件路径: {pcap_path}\n"
            if pcap_path
            else "- PCAP文件路径: 无（使用默认初始参数）\n"
        )
        user_message = (
            "请开始闭环网络实验：\n"
            f"- 目标IP: {target_ip}\n"
            f"- 最大迭代次数: {max_iters}\n"
            f"- 无改善停止轮数: {no_improve_limit}\n"
            f"- 日志文件路径: {log_path}\n"
            + pcap_line +
            "\n请严格按照系统提示中的实验协议执行。"
            "如果提供了PCAP文件，先用 pcap_profile 工具分析流量特征。"
        )

        initial_state = {"messages": [{"role": "user", "content": user_message}]}

        logger.info("Starting experiment: thread=%s, target=%s", thread_id, target_ip)

        try:
            await self._run_loop(initial_state)
        except Exception as e:
            logger.exception("Experiment error")
            await websocket.send_json({
                "type": "error",
                "data": {"message": str(e)},
            })
        finally:
            self._running = False
            self._ws = None
            await websocket.send_json({
                "type": "experiment_done",
                "data": {"message": "实验已结束"},
            })

    async def approve(self, approved: bool) -> None:
        """Signal HITL approval result into the experiment's queue."""
        if self._hitl_queue:
            await self._hitl_queue.put(approved)

    async def stop(self) -> None:
        """Request graceful stop of the current experiment."""
        self._stop_requested = True
        if self._hitl_queue:
            await self._hitl_queue.put(False)

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

            await ws.send_json({"type": "hitl_request", "data": hitl_info})

            approved = await self._hitl_queue.get()

            await ws.send_json({
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
                    ws.send_json({
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
                await self._ws.send_json({"type": "tool_result", "data": msg_dict})
            else:
                await self._ws.send_json({"type": "messages", "data": [msg_dict]})

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
