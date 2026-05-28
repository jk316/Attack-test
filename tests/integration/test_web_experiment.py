"""Integration test for the web experiment flow."""
import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest


def _make_state(next_nodes, msg_list, tasks=None):
    msgs = []
    for role, content, tc in msg_list:
        m = MagicMock()
        m.type = role
        m.content = content
        m.tool_calls = tc
        msgs.append(m)

    gs = MagicMock()
    gs.next = next_nodes
    gs.values = {"messages": msgs}
    gs.tasks = tasks or []
    return gs


@pytest.mark.asyncio
async def test_run_loop_single_hitl_cycle():
    """Agent calls traffic_send → interrupt → approve → agent finishes."""
    from backend.experiment import ExperimentManager

    manager = ExperimentManager()

    fake_graph = MagicMock()
    fake_graph.ainvoke = AsyncMock()
    fake_graph.get_state = MagicMock()
    manager._graph = fake_graph

    paused = _make_state(
        ("tools",),
        [("human", "start", None),
         ("ai", "Calling traffic_send", [{"name": "traffic_send", "args": {}, "id": "t1"}])],
        [MagicMock(interrupts=[MagicMock(value={"message": "[HITL] Approve?", "params": {"pps": 10}})])],
    )
    completed = _make_state(
        (),
        [("human", "start", None),
         ("ai", "Calling traffic_send", [{"name": "traffic_send", "args": {}, "id": "t1"}]),
         ("ai", "Approved, sending", None),
         ("tool", "sent 50 packets", None),
         ("ai", "Experiment done!", None)],
    )

    # get_state call order: push before loop, loop check, push after resume, loop check, final
    fake_graph.get_state.side_effect = [paused, paused, completed, completed, completed]

    sent = []

    class FakeWS:
        async def send_json(self, data):
            sent.append(data)

    manager._ws = FakeWS()
    manager._config = {"configurable": {"thread_id": "test"}}

    async def approve_soon():
        await asyncio.sleep(0.3)
        await manager.approve(True)

    task_run = asyncio.create_task(
        manager._run_loop({"messages": [{"role": "user", "content": "start"}]})
    )
    asyncio.create_task(approve_soon())

    await asyncio.wait_for(task_run, timeout=10)

    types = [m["type"] for m in sent if "type" in m]
    print("Types:", types)
    assert "hitl_request" in types, f"Missing HITL request: {types}"
    assert "hitl_response" in types, f"Missing HITL response: {types}"


@pytest.mark.asyncio
async def test_run_loop_no_hitl_just_completes():
    """Agent completes without any HITL tool calls."""
    from backend.experiment import ExperimentManager

    manager = ExperimentManager()

    fake_graph = MagicMock()
    fake_graph.ainvoke = AsyncMock()
    fake_graph.get_state = MagicMock()
    manager._graph = fake_graph

    done = _make_state(
        (),
        [("human", "start", None), ("ai", "Done!", None)],
    )
    fake_graph.get_state.side_effect = [done, done, done]  # push, loop check, final

    sent = []

    class FakeWS:
        async def send_json(self, data):
            sent.append(data)

    manager._ws = FakeWS()
    manager._config = {"configurable": {"thread_id": "test"}}

    await manager._run_loop({"messages": [{"role": "user", "content": "start"}]})

    types = [m["type"] for m in sent if "type" in m]
    print("Types:", types)
    assert "hitl_request" not in types, "No HITL needed"
    assert any(t == "messages" for t in types)


def test_extract_hitl_from_tasks():
    from backend.experiment import ExperimentManager
    fake_intr = MagicMock()
    fake_intr.value = {"message": "[HITL]", "params": {}}
    fake_task = MagicMock()
    fake_task.interrupts = [fake_intr]
    fake_gs = MagicMock()
    fake_gs.tasks = [fake_task]
    assert ExperimentManager._extract_hitl(fake_gs) is not None


def test_extract_hitl_returns_none_for_no_tasks():
    from backend.experiment import ExperimentManager
    assert ExperimentManager._extract_hitl(MagicMock(tasks=[])) is None


def test_msg_to_dict_conversions():
    from backend.experiment import _msg_to_dict
    ai = MagicMock()
    ai.type = "ai"
    ai.content = "hi"
    ai.tool_calls = [{"name": "t", "args": {}}]
    r = _msg_to_dict(ai)
    assert r["role"] == "ai"
    assert len(r["tool_calls"]) == 1
