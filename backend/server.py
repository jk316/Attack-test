"""FastAPI server for the closed-loop experiment web console.

Provides WebSocket for real-time agent state streaming,
REST endpoints for experiment control and PCAP upload,
and serves the static frontend files.
"""
import asyncio
import json
import uuid
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.experiment import ExperimentManager

app = FastAPI(title="Closed-Loop Experiment Console")

# Serve frontend static files
_FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "uploads"
_DATA_DIR.mkdir(parents=True, exist_ok=True)

manager = ExperimentManager()


# ── Pydantic models ────────────────────────────────────────────

class StartRequest(BaseModel):
    target_ip: str = "10.99.80.160"
    pcap_path: str = ""
    log_path: str = "data/experiment.jsonl"
    max_iters: int = 20
    no_improve_limit: int = 5


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
    return {
        "success": True,
        "message": "实验参数已验证。请通过 WebSocket 启动实验以接收实时消息。",
        "params": req.model_dump(),
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
    """Upload a PCAP/PCAPng file for traffic profiling."""
    if not file.filename:
        return {"success": False, "error": "未选择文件"}

    safe_name = f"{uuid.uuid4().hex[:8]}_{file.filename}"
    dest = _DATA_DIR / safe_name
    content = await file.read()
    dest.write_bytes(content)

    return {
        "success": True,
        "file_path": str(dest.relative_to(Path(__file__).resolve().parent.parent)),
        "file_name": file.filename,
        "size_bytes": len(content),
    }
