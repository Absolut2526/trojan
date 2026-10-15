import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

# Ensure server directory is in sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import config
from connection_manager import manager
from bot import get_bot_instance, dp, notify_pc_status

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

bot_polling_task = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Start aiogram bot polling if BOT_TOKEN is present
    global bot_polling_task
    bot = get_bot_instance()
    if bot:
        logger.info("Starting Telegram Bot polling...")
        bot_polling_task = asyncio.create_task(dp.start_polling(bot))
    else:
        logger.warning("BOT_TOKEN is not configured! Telegram bot is disabled.")

    yield

    # Shutdown: Stop bot
    if bot_polling_task:
        logger.info("Stopping Telegram Bot polling...")
        bot_polling_task.cancel()
        try:
            await bot_polling_task
        except asyncio.CancelledError:
            pass
    if bot:
        await bot.session.close()

app = FastAPI(title="PC Club Manager", lifespan=lifespan)

# Mount static files
WEB_DIR = os.path.join(BASE_DIR, "web")
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

@app.middleware("http")
async def add_no_cache_header(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

@app.get("/")
async def get_index():
    return FileResponse(
        os.path.join(WEB_DIR, "index.html"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )

# --- WebSocket for Club PC Clients ---
@app.websocket("/ws/client/{pc_name}")
async def websocket_client_endpoint(
    websocket: WebSocket,
    pc_name: str,
    secret: str = Query(...),
    hwid: Optional[str] = Query(None)
):
    # Verify secret: accept configured secret, or default club secret
    valid_secrets = {config.CLIENT_SECRET, "super_secret_club_key_2026", "pc_club_secret_key_123"}
    valid_secrets.discard("")
    if valid_secrets and secret not in valid_secrets:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        logger.warning(f"Rejected connection from '{pc_name}': invalid secret.")
        return

    # Якщо клієнт передав свій унікальний HWID — закріплюємо або видаємо йому постійне ім'я (PC-01, PC-02...)
    if hwid:
        assigned_name = manager.get_or_assign_pc_name(hwid)
        if assigned_name != pc_name:
            logger.info(f"Клієнт підключився як '{pc_name}', але за HWID йому призначено '{assigned_name}'")
            pc_name = assigned_name

    await manager.connect_client(pc_name, websocket)
    # Повідомляємо клієнту його офіційне ім'я
    await websocket.send_json({"type": "assigned_name", "pc_name": pc_name})
    asyncio.create_task(notify_pc_status(pc_name, "online"))
    # Автоматично запускаємо трансляцію екрану при підключенні ПК
    asyncio.create_task(manager.send_command(pc_name, "start_stream", {"fps": 8}))

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "response":
                # Response to a previously sent command
                handled = manager.handle_client_response(data)
                # Помилка fire-and-forget команди (рух мишi тощо) — показуємо її в дашборді,
                # бо інакше збій на ПК залишається непомітним
                if not handled and data.get("status") == "error":
                    await manager.broadcast_to_dashboards({
                        "type": "control_error",
                        "pc": pc_name,
                        "action": data.get("action"),
                        "message": data.get("message") or "Невідома помилка на ПК"
                    })

            elif msg_type == "heartbeat":
                # Heartbeat with CPU/RAM stats
                stats = data.get("stats", {})
                manager.update_client_stats(pc_name, stats)
                await manager.broadcast_to_dashboards({"type": "stats_update", "pc": pc_name, "stats": stats})

            elif msg_type == "stream_frame":
                # Forward live screen frame to dashboards
                await manager.broadcast_to_dashboards({
                    "type": "stream_frame",
                    "pc": pc_name,
                    "frame": data.get("frame")
                })

            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        manager.disconnect_client(pc_name, websocket)
        asyncio.create_task(notify_pc_status(pc_name, "offline"))
    except Exception as e:
        logger.error(f"WebSocket client error ({pc_name}): {e}")
        manager.disconnect_client(pc_name, websocket)
        asyncio.create_task(notify_pc_status(pc_name, "offline"))

# --- WebSocket for Dashboard ---
@app.websocket("/ws/dashboard")
async def websocket_dashboard_endpoint(websocket: WebSocket):
    await manager.connect_dashboard(websocket)
    # При підключенні дашборду гарантуємо, що всі онлайн ПК транслюють екран
    for active_pc in list(manager.active_clients.keys()):
        asyncio.create_task(manager.send_command(active_pc, "start_stream", {"fps": 8}))
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            # Керування ПК напряму з дашборду (миша, скрол тощо) —
            # без HTTP-запиту й без очікування відповіді, щоб не втрачати плавність
            if data.get("type") == "control":
                target_pc = data.get("pc")
                action = data.get("action")
                params = data.get("params") or {}
                if not target_pc or not action:
                    continue
                if not manager.is_online(target_pc):
                    continue
                asyncio.create_task(manager.send_action(target_pc, action, params))
    except WebSocketDisconnect:
        manager.disconnect_dashboard(websocket)
    except Exception:
        manager.disconnect_dashboard(websocket)

# --- REST APIs for Web UI ---
@app.get("/api/pcs")
async def api_get_pcs():
    return manager.get_all_pcs()

class CommandRequest(BaseModel):
    action: str
    params: Dict[str, Any] = {}

@app.post("/api/pcs/broadcast/command")
async def api_broadcast_command(req: CommandRequest):
    result = await manager.send_broadcast_command(req.action, req.params)
    return result

@app.post("/api/pcs/{pc_name}/command")
async def api_send_command(pc_name: str, req: CommandRequest):
    if not manager.is_online(pc_name):
        raise HTTPException(status_code=400, detail=f"Комп'ютер '{pc_name}' не в мережі.")

    result = await manager.send_command(pc_name, req.action, req.params)
    return result

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=True)
