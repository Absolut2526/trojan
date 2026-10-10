import asyncio
import base64
import io
import json
import logging
import os
import platform
import socket
import sys
import webbrowser
from typing import Any, Dict

import psutil
import websockets
from PIL import ImageGrab

if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(BASE_DIR, "client_config.json")
LOG_FILE = os.path.join(BASE_DIR, "client.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("PC-Client")

def load_or_create_config() -> dict:
    default_name = socket.gethostname()
    default_config = {
        "server_url": "ws://localhost:8000/ws/client",
        "secret": "pc_club_secret_key_123",
        "pc_name": default_name
    }

    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(default_config, f, indent=4)
        logger.info(f"Створено конфігураційний файл '{CONFIG_FILE}' з іменем ПК: {default_name}")
        return default_config

    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Помилка читання {CONFIG_FILE}: {e}")
        return default_config

def get_screenshot_base64() -> str:
    """Робить скріншот екрану та повертає його у форматі Base64 JPEG."""
    try:
        img = ImageGrab.grab()
        buffer = io.BytesIO()
        # Зберігаємо як JPEG з оптимізацією для швидкої передачі через інтернет
        img.convert("RGB").save(buffer, format="JPEG", quality=75, optimize=True)
        encoded = base64.b64encode(buffer.getvalue()).decode("utf-8")
        return encoded
    except Exception as e:
        logger.error(f"Помилка створення скріншоту: {e}")
        raise

def kill_process_by_name(target_name: str) -> int:
    """Завершує процес(и) за назвою (наприклад, dota2.exe або steam)."""
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
    """Повертає список процесів, відсортованих за використанням RAM."""
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
    system = platform.system().lower()
    if "windows" in system:
        os.system("shutdown /s /t 0")
    elif "darwin" in system:
        os.system("osascript -e 'tell app \"System Events\" to shut down'")
    else:
        os.system("shutdown -h now")

def execute_restart():
    system = platform.system().lower()
    if "windows" in system:
        os.system("shutdown /r /t 0")
    elif "darwin" in system:
        os.system("osascript -e 'tell app \"System Events\" to restart'")
    else:
        os.system("shutdown -r now")

async def execute_action(action: str, params: dict) -> dict:
    """Обробляє команди з сервера."""
    try:
        if action == "screenshot":
            img_b64 = get_screenshot_base64()
            return {"status": "ok", "image_base64": img_b64}

        elif action == "open_url":
            url = params.get("url")
            if not url:
                return {"status": "error", "message": "Не вказано URL"}
            webbrowser.open(url)
            return {"status": "ok", "message": f"URL {url} відкрито"}

        elif action == "kill_process":
            proc_name = params.get("name")
            if not proc_name:
                return {"status": "error", "message": "Не вказано назву процесу"}
            killed = kill_process_by_name(proc_name)
            if killed > 0:
                return {"status": "ok", "killed_count": killed}
            else:
                return {"status": "error", "message": f"Процес '{proc_name}' не знайдено"}

        elif action == "list_processes":
            procs = get_process_list()
            return {"status": "ok", "processes": procs}

        elif action == "restart":
            # Виконуємо з невеликою затримкою, щоб встигнути відповісти серверу
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
    """Періодично відправляє навантаження CPU та RAM."""
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
    cfg = load_or_create_config()
    server_base = cfg["server_url"].rstrip("/")
    secret = cfg["secret"]
    pc_name = cfg["pc_name"]

    uri = f"{server_base}/{pc_name}?secret={secret}"
    logger.info(f"Підключення до сервера як '{pc_name}'...")

    while True:
        try:
            async with websockets.connect(uri, ping_interval=20, ping_timeout=20) as websocket:
                logger.info(f"✅ Успішно підключено до сервера як {pc_name}!")
                
                # Запускаємо фонову відправку системної статистики
                heartbeat_task = asyncio.create_task(heartbeat_sender(websocket))

                try:
                    async for message_str in websocket:
                        try:
                            msg = json.loads(message_str)
                            req_id = msg.get("request_id")
                            action = msg.get("action")
                            params = msg.get("params", {})

                            logger.info(f"Отримано команду: {action}")
                            result = await execute_action(action, params)

                            # Відправляємо результат назад серверу
                            response_payload = {
                                "type": "response",
                                "request_id": req_id,
                                **result
                            }
                            await websocket.send(json.dumps(response_payload))
                        except json.JSONDecodeError:
                            logger.warning(f"Невірний формат повідомлення: {message_str}")
                finally:
                    heartbeat_task.cancel()

        except (websockets.ConnectionClosedError, websockets.WebSocketException, OSError) as e:
            logger.warning(f"З'єднання втрачено: {e}. Спроба перепідключення через 5 секунд...")
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Непередбачена помилка: {e}. Перепідключення через 5 секунд...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(run_client())
    except KeyboardInterrupt:
        logger.info("Клієнт зупинено користувачем.")
