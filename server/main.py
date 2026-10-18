import asyncio
import hashlib
import hmac
import json
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

# Ensure server directory is in sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException, status, Request, Depends
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import config
from connection_manager import manager
from bot import get_bot_instance, dp, notify_pc_status

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

bot_polling_task = None

AUTH_COOKIE_NAME = "pc_club_session"

def _get_session_secret() -> bytes:
    pwd = config.DASHBOARD_PASSWORD or "admin123"
    return hashlib.sha256(f"pc_club_session_salt_{pwd}".encode()).digest()

def create_session_token() -> str:
    # 30 days validity
    expires_at = int(time.time()) + 30 * 86400
    payload = str(expires_at).encode()
    signature = hmac.new(_get_session_secret(), payload, hashlib.sha256).hexdigest()
    return f"{expires_at}.{signature}"

def verify_session_token(token: Optional[str]) -> bool:
    if not token or "." not in token:
        return False
    try:
        expires_at_str, signature = token.split(".", 1)
        expires_at = int(expires_at_str)
        if time.time() > expires_at:
            return False
        expected_sig = hmac.new(_get_session_secret(), str(expires_at).encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature, expected_sig)
    except Exception:
        return False

def require_dashboard_auth(request: Request):
    token = request.cookies.get(AUTH_COOKIE_NAME)
    if not token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
    if not verify_session_token(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Потрібна авторизація"
        )

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
async def add_no_cache_header(request: Request, call_next):
    # Prevent direct static access to index.html or login.html without routing
    if request.url.path in ("/static/index.html", "/static/login.html"):
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)

    response = await call_next(request)
    if request.url.path.startswith("/static/") or request.url.path in ("/", "/login"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

@app.get("/")
async def get_index(request: Request):
    token = request.cookies.get(AUTH_COOKIE_NAME)
    if not verify_session_token(token):
        return RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    return FileResponse(
        os.path.join(WEB_DIR, "index.html"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )

@app.get("/login")
async def get_login(request: Request):
    token = request.cookies.get(AUTH_COOKIE_NAME)
    if verify_session_token(token):
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    return FileResponse(
        os.path.join(WEB_DIR, "login.html"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
    )

class LoginRequest(BaseModel):
    password: str

@app.post("/api/login")
async def api_login(req: LoginRequest):
    expected_password = config.DASHBOARD_PASSWORD or "admin123"
    if not hmac.compare_digest(req.password.strip(), expected_password.strip()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невірний пароль. Спробуйте ще раз."
        )
    token = create_session_token()
    response = JSONResponse(content={"status": "ok", "message": "Авторизація успішна"})
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=token,
        max_age=30 * 86400,
        httponly=True,
        samesite="lax",
        secure=False
    )
    return response

@app.post("/api/logout")
async def api_logout():
    response = JSONResponse(content={"status": "ok", "message": "Вихід виконано"})
    response.delete_cookie(key=AUTH_COOKIE_NAME)
    return response

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

    await manager.connect_client(pc_name, websocket, hwid=hwid)
    # Повідомляємо клієнту його офіційне ім'я
    await websocket.send_json({"type": "assigned_name", "pc_name": pc_name})
    asyncio.create_task(notify_pc_status(pc_name, "online"))
    # Автоматично запускаємо трансляцію екрану при підключенні ПК
    asyncio.create_task(manager.send_command(pc_name, "start_stream", {"fps": 8}))

    try:
        while True:
            data = await websocket.receive_json()
            # Отримуємо актуальне ім'я ПК (на випадок якщо його перейменували під час підключення)
            current_pc = manager.get_name_by_websocket(websocket) or pc_name
            msg_type = data.get("type")

            if msg_type == "response":
                # Response to a previously sent command
                handled = manager.handle_client_response(data)
                # Помилка fire-and-forget команди (рух мишi тощо) — показуємо її в дашборді,
                # бо інакше збій на ПК залишається непомітним
                if not handled and data.get("status") == "error":
                    await manager.broadcast_to_dashboards({
                        "type": "control_error",
                        "pc": current_pc,
                        "action": data.get("action"),
                        "message": data.get("message") or "Невідома помилка на ПК"
                    })

            elif msg_type == "heartbeat":
                # Heartbeat with CPU/RAM stats
                stats = data.get("stats", {})
                manager.update_client_stats(current_pc, stats)
                await manager.broadcast_to_dashboards({"type": "stats_update", "pc": current_pc, "stats": stats})

            elif msg_type == "stream_frame":
                # Forward live screen frame to dashboards
                await manager.broadcast_to_dashboards({
                    "type": "stream_frame",
                    "pc": current_pc,
                    "frame": data.get("frame")
                })

            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})

    except WebSocketDisconnect:
        current_pc = manager.get_name_by_websocket(websocket) or pc_name
        manager.disconnect_client(current_pc, websocket)
        asyncio.create_task(notify_pc_status(current_pc, "offline"))
    except Exception as e:
        current_pc = manager.get_name_by_websocket(websocket) or pc_name
        logger.error(f"WebSocket client error ({current_pc}): {e}")
        manager.disconnect_client(current_pc, websocket)
        asyncio.create_task(notify_pc_status(current_pc, "offline"))

# --- WebSocket for Dashboard ---
@app.websocket("/ws/dashboard")
async def websocket_dashboard_endpoint(websocket: WebSocket):
    token = websocket.cookies.get(AUTH_COOKIE_NAME) or websocket.query_params.get("token")
    if not verify_session_token(token):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        logger.warning("Rejected dashboard WebSocket connection: unauthorized.")
        return

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
@app.get("/api/pcs", dependencies=[Depends(require_dashboard_auth)])
async def api_get_pcs():
    return manager.get_all_pcs()

class CommandRequest(BaseModel):
    action: str
    params: Dict[str, Any] = {}

@app.post("/api/pcs/broadcast/command", dependencies=[Depends(require_dashboard_auth)])
async def api_broadcast_command(req: CommandRequest):
    result = await manager.send_broadcast_command(req.action, req.params)
    return result

@app.post("/api/pcs/{pc_name}/command", dependencies=[Depends(require_dashboard_auth)])
async def api_send_command(pc_name: str, req: CommandRequest):
    if not manager.is_online(pc_name):
        raise HTTPException(status_code=400, detail=f"Комп'ютер '{pc_name}' не в мережі.")

    result = await manager.send_command(pc_name, req.action, req.params)
    return result

class RenameRequest(BaseModel):
    new_name: str

@app.post("/api/pcs/{pc_name}/rename", dependencies=[Depends(require_dashboard_auth)])
async def api_rename_pc(pc_name: str, req: RenameRequest):
    result = await manager.rename_pc(pc_name, req.new_name)
    if result.get("status") != "ok":
        raise HTTPException(status_code=400, detail=result.get("message", "Помилка перейменування"))
    return result

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=config.HOST, port=config.PORT, reload=True)
