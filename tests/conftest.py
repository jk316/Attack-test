"""Project-wide pytest fixtures (all test directories).

R9（Lead 裁定，005 梯队执行）: ``src/main.py::main()`` 的日志初始化对
``"agent"`` logger 设 ``propagate = False`` 并附加 console/file handler，
且不恢复。e2e/integration 测试调用 ``main()`` 后，后续测试（如
``test_verbose_callback.py`` 的 caplog 断言）捕获不到记录，且旧
StreamHandler 写入 pytest 已关闭的捕获流报 "I/O operation on closed file"。
本文件用 autouse fixture 在每个测试前后快照/恢复 logger 状态，
纯测试侧修复，不改生产代码。
"""

import logging
import sys
from pathlib import Path

import pytest

# Add project root to path so `from src.tools.xxx` imports work
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(autouse=True)
def _isolate_agent_logger_state():
    """R9: 快照并恢复 "agent" logger 与 root logger 的可变状态。

    防止 main()（e2e/integration 测试中被调用）设置的 propagate=False
    与新附加的 handler 泄漏到后续测试。
    """
    agent = logging.getLogger("agent")
    root = logging.getLogger()
    saved_handlers = list(agent.handlers)
    saved_level = agent.level
    saved_propagate = agent.propagate
    saved_root_level = root.level
    yield
    agent.handlers[:] = saved_handlers
    agent.setLevel(saved_level)
    agent.propagate = saved_propagate
    root.setLevel(saved_root_level)
