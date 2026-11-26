"""FastAPI server for the closed-loop experiment web console.

Provides WebSocket for real-time agent state streaming,
REST endpoints for experiment control and PCAP upload,
and serves the static frontend files.
"""
import asyncio
import json
import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from backend.experiment import ExperimentManager

logger = logging.getLogger("experiment.server")

app = FastAPI(title="Closed-Loop Experiment Console")

# Serve the built React frontend (frontend-react/dist). Build with:
#   cd frontend-react && npm install && npm run build
_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend-react" / "dist"
_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "uploads"
_DATA_DIR.mkdir(parents=True, exist_ok=True)

# ── 配置单一来源（宪法六 / 007-G4）──────────────────────────────
_EXPERIMENT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "experiment.json"


def _load_defaults() -> dict:
    """启动时从 experiment.json 读取默认值（读取失败返回空 dict，逐字段兜底）。"""
    try:
        with open(_EXPERIMENT_CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


_DEFAULTS = _load_defaults()

# ── PCAP 上传校验（007-3 决议 / G3 / FR-015/016）─────────────────
ALLOWED_UPLOAD_EXTENSIONS = {".pcap", ".pcapng", ".cap"}
MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100MB

manager = ExperimentManager()

# ── 内网限定声明（007-1 决议，T023）：启动即 WARNING ────────────
logger.warning(
    "Web 控制台仅限可信内网使用：本服务无身份认证，任何能访问此地址的人"
    "都可以启动实验并做出 HITL 审批，请勿暴露于公网。"
)


# ── Pydantic models ────────────────────────────────────────────

class StartRequest(BaseModel):
    target_ip: str = Field(
        default_factory=lambda: _DEFAULTS.get("target_ip", "100.1.11.20"))
    pcap_path: str = ""
    log_path: str = "data/experiment.jsonl"
    max_iters: int = Field(
        default_factory=lambda: _DEFAULTS.get("max_iters", 20))
    no_improve_limit: int = Field(
        default_factory=lambda: _DEFAULTS.get("no_improve_limit", 5))


# ── Static file serving ────────────────────────────────────────
app.mount("/static", StaticFiles(directory=str(_FRONTEND_DIR)), name="static")


@app.get("/")
async def root():
    return FileResponse(_FRONTEND_DIR / "index.html")


# ── WebSocket (main communication channel) ─────────────────────

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await websocket.accept()
    await websocket.send_json({
        "type": "status",
        "data": {"status": "connected", "client_id": client_id},
    })

    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)
            msg_type = data.get("type")
            payload = data.get("data", {})

            if msg_type == "start_experiment":
                asyncio.create_task(manager.start(payload, websocket))

            elif msg_type == "hitl_response":
                approved = payload.get("approved", False)
                await manager.approve(approved)

            elif msg_type == "stop_experiment":
                await manager.stop()

            else:
                await websocket.send_json({
                    "type": "error",
                    "data": {"message": f"未知消息类型: {msg_type}"},
                })
    except WebSocketDisconnect:
        pass  # Client disconnected — gracefully clean up
    except json.JSONDecodeError:
        await websocket.send_json({
            "type": "error",
            "data": {"message": "无效的 JSON"},
        })
    except Exception as e:
        await websocket.send_json({
            "type": "error",
            "data": {"message": str(e)},
        })


# ── REST endpoints ─────────────────────────────────────────────

@app.post("/api/experiment/start")
async def api_start(req: StartRequest):
    """HTTP endpoint to start an experiment (returns immediately).

    The actual experiment runs via WebSocket — this just validates params.
    """
    # data-model「实验运行」约束字段：max_iters/no_improve_limit ≥1
    for name, value in (("max_iters", req.max_iters),
                        ("no_improve_limit", req.no_improve_limit)):
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            return JSONResponse(
                status_code=400,
                content={"success": False, "error": f"{name} 必须为 ≥1 的整数"},
            )
    return {
        "success": True,
        "message": "实验参数已验证。请通过 WebSocket 启动实验以接收实时消息。",
        "params": req.model_dump(),
    }


@app.get("/api/experiment/defaults")
async def api_defaults():
    """实验默认值（单一来源：experiment.json；007-G4 / 宪法六）。"""
    return {
        "target_ip": _DEFAULTS.get("target_ip", "100.1.11.20"),
        "max_iters": _DEFAULTS.get("max_iters", 20),
        "no_improve_limit": _DEFAULTS.get("no_improve_limit", 5),
    }


@app.post("/api/experiment/stop")
async def api_stop():
    """Stop the currently running experiment."""
    await manager.stop()
    return {"success": True, "message": "停止请求已发送"}


@app.get("/api/experiment/status")
async def api_status():
    """Get current experiment status."""
    return {"running": manager.running}


@app.post("/api/upload/pcap")
async def api_upload_pcap(file: UploadFile = File(...)):
    """Upload a PCAP/PCAPng file for traffic profiling.

    G3（007-3 决议）：服务端强制扩展名白名单 + 100MB 上限；校验失败不落盘。
    """
    if not file.filename:
        return JSONResponse(status_code=400,
                            content={"success": False, "error": "未选择文件"})

    # 仅取纯文件名（防路径穿越），扩展名白名单不区分大小写
    bare_name = Path(file.filename).name
    ext = Path(bare_name).suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        return JSONResponse(
            status_code=400,
            content={"success": False,
                     "error": "不支持的文件类型（仅 .pcap/.pcapng/.cap）"},
        )

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        return JSONResponse(
            status_code=413,
            content={"success": False, "error": "文件超过大小上限（100MB）"},
        )

    safe_name = f"{uuid.uuid4().hex[:8]}_{bare_name}"
    dest = _DATA_DIR / safe_name
    dest.write_bytes(content)

    project_root = Path(__file__).resolve().parent.parent
    try:
        rel_path = str(dest.relative_to(project_root))
    except ValueError:
        # 上传目录被重定向（测试/部署）时回退契约形态
        rel_path = f"data/uploads/{dest.name}"

    return {
        "success": True,
        "file_path": rel_path,
        "file_name": bare_name,
        "size_bytes": len(content),
    }
