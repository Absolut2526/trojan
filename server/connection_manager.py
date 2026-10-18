import asyncio
import json
import logging
import os
import time
import uuid
from typing import Dict, Any, Optional
from fastapi import WebSocket

logger = logging.getLogger(__name__)

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pcs_registry.json")

class ConnectionManager:
    def __init__(self):
        # pc_name -> WebSocket
        self.active_clients: Dict[str, WebSocket] = {}
        # pc_name -> dict with specs/last_seen/stats
        self.client_info: Dict[str, Dict[str, Any]] = {}
        # hwid -> pc_name
        self.hwid_mapping: Dict[str, str] = self._load_registry()
        # Попередньо заповнюємо збережені ПК як offline, щоб їхні імена були відомі
        for h, n in self.hwid_mapping.items():
            self.client_info[n] = {
                "name": n,
                "status": "offline",
                "info": {},
                "connected_at": None,
                "hwid": h
            }
        # request_id -> asyncio.Future for command responses
        self.pending_requests: Dict[str, asyncio.Future] = {}
        # Web dashboard sockets
        self.dashboard_sockets: list[WebSocket] = []

    def _load_registry(self) -> Dict[str, str]:
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Помилка завантаження pcs_registry.json: {e}")
        return {}

    def _save_registry(self):
        try:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(self.hwid_mapping, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Помилка збереження pcs_registry.json: {e}")

    def get_hwid_by_pc_name(self, pc_name: str) -> Optional[str]:
        """Повертає HWID комп'ютера за його назвою."""
        # 1. Перевіряємо в client_info
        if pc_name in self.client_info and self.client_info[pc_name].get("hwid"):
            return self.client_info[pc_name]["hwid"]
        # 2. Шукаємо у hwid_mapping
        for h, name in self.hwid_mapping.items():
            if name == pc_name:
                return h
        return None

    def get_or_assign_pc_name(self, hwid: str) -> str:
        """
        Повертає закріплене ім'я ПК для даного заліза (HWID).
        Якщо ПК перейменовано — завжди повертає його нове збережене ім'я.
        Якщо новий — призначає найменший вільний номер (PC-01, PC-02...).
        """
        if hwid in self.hwid_mapping:
            return self.hwid_mapping[hwid]

        # Знаходимо найменший вільний номер
        existing_numbers = set()
        for name in self.hwid_mapping.values():
            if name.startswith("PC-"):
                num_part = name.split("-")[1]
                if num_part.isdigit():
                    existing_numbers.add(int(num_part))

        next_num = 1
        while next_num in existing_numbers:
            next_num += 1

        assigned_name = f"PC-{next_num:02d}"
        self.hwid_mapping[hwid] = assigned_name
        self._save_registry()
        logger.info(f"Нове залізо HWID={hwid} зареєстровано як '{assigned_name}'")
        return assigned_name

    async def rename_pc(self, old_name: str, new_name: str) -> Dict[str, Any]:
        """
        Перейменовує комп'ютер та назавжди зберігає його нове ім'я за HWID.
        """
        old_name = old_name.strip()
        new_name = new_name.strip()

        if not new_name:
            return {"status": "error", "message": "Назва комп'ютера не може бути порожньою."}

        if len(new_name) > 32:
            return {"status": "error", "message": "Назва комп'ютера не може бути довшою за 32 символи."}

        invalid_chars = set('/\\?%#:*"<>|')
        if any(c in invalid_chars for c in new_name):
            return {"status": "error", "message": "Назва містить неприпустимі символи (/ \\ ? % # : * \" < > |)."}

        if old_name == new_name:
            return {"status": "ok", "message": "Назва не змінилася.", "pc_name": new_name}

        # Перевірка на конфлікт імен з іншими ПК
        for h, n in self.hwid_mapping.items():
            if n.lower() == new_name.lower() and n != old_name:
                return {"status": "error", "message": f"Комп'ютер з назвою '{new_name}' вже зареєстрований."}

        for n in self.client_info.keys():
            if n.lower() == new_name.lower() and n != old_name:
                return {"status": "error", "message": f"Комп'ютер з назвою '{new_name}' вже онлайн."}

        # Знаходимо HWID комп'ютера
        hwid = self.get_hwid_by_pc_name(old_name)
        if not hwid:
            # Якщо HWID не був зафіксований раніше, генеруємо стабільний ключ за старим іменем
            hwid = f"pc_{old_name}"

        # Оновлюємо та зберігаємо у базі
        self.hwid_mapping[hwid] = new_name
        self._save_registry()

        # Оновлюємо живі підключення та пам'ять
        is_online = old_name in self.active_clients
        ws = None
        if is_online:
            ws = self.active_clients.pop(old_name)
            self.active_clients[new_name] = ws

        if old_name in self.client_info:
            info_dict = self.client_info.pop(old_name)
            info_dict["name"] = new_name
            info_dict["hwid"] = hwid
            self.client_info[new_name] = info_dict
        else:
            self.client_info[new_name] = {
                "name": new_name,
                "status": "online" if is_online else "offline",
                "info": {},
                "connected_at": time.time() if is_online else None,
                "hwid": hwid
            }

        # Сповіщаємо сам комп'ютер, щоб він оновив локальний файл client_config.json
        if ws:
            try:
                await ws.send_text(json.dumps({
                    "type": "assigned_name",
                    "pc_name": new_name
                }))
            except Exception as e:
                logger.error(f"Помилка відправки нового імені клієнту {new_name}: {e}")

        # Сповіщаємо всі відкриті веб-панелі (дашборди)
        await self.broadcast_to_dashboards({
            "type": "pc_renamed",
            "old_name": old_name,
            "new_name": new_name
        })

        logger.info(f"Комп'ютер '{old_name}' успішно перейменовано на '{new_name}' (HWID={hwid})")
        return {
            "status": "ok",
            "message": f"ПК успішно перейменовано на '{new_name}'",
            "old_name": old_name,
            "new_name": new_name
        }

    async def connect_client(
        self,
        pc_name: str,
        websocket: WebSocket,
        initial_info: Optional[Dict[str, Any]] = None,
        hwid: Optional[str] = None
    ):
        if pc_name in self.active_clients:
            old_ws = self.active_clients[pc_name]
            try:
                await old_ws.close()
            except Exception:
                pass
        await websocket.accept()
        now = time.time()
        self.active_clients[pc_name] = websocket
        existing_info = self.client_info.get(pc_name, {})
        self.client_info[pc_name] = {
            "name": pc_name,
            "status": "online",
            "info": initial_info or existing_info.get("info", {}),
            "connected_at": now,
            "hwid": hwid or existing_info.get("hwid") or self.get_hwid_by_pc_name(pc_name)
        }
        logger.info(f"Client '{pc_name}' connected (HWID={self.client_info[pc_name]['hwid']}).")
        await self.broadcast_to_dashboards({
            "type": "pc_status_change",
            "pc": pc_name,
            "status": "online",
            "connected_at": now
        })

    def get_name_by_websocket(self, websocket: WebSocket) -> Optional[str]:
        """Знаходить поточне ім'я комп'ютера за його активним WebSocket об'єктом."""
        for name, ws in self.active_clients.items():
            if ws == websocket:
                return name
        return None

    def disconnect_client(self, pc_name: str, websocket: Optional[WebSocket] = None):
        target_name = pc_name
        if websocket and (target_name not in self.active_clients or self.active_clients[target_name] != websocket):
            found = self.get_name_by_websocket(websocket)
            if found:
                target_name = found

        if target_name in self.active_clients:
            if websocket is None or self.active_clients[target_name] == websocket:
                del self.active_clients[target_name]
                if target_name in self.client_info:
                    self.client_info[target_name]["status"] = "offline"
                    self.client_info[target_name]["connected_at"] = None
                logger.info(f"Client '{target_name}' disconnected.")
                asyncio.create_task(
                    self.broadcast_to_dashboards({"type": "pc_status_change", "pc": target_name, "status": "offline"})
                )

    def is_online(self, pc_name: str) -> bool:
        return pc_name in self.active_clients

    def get_all_pcs(self) -> Dict[str, Dict[str, Any]]:
        result = {}
        for name, data in self.client_info.items():
            is_online = name in self.active_clients
            result[name] = {
                "name": name,
                "status": "online" if is_online else "offline",
                "info": data.get("info", {}),
                "connected_at": data.get("connected_at") if is_online else None,
                "hwid": data.get("hwid")
            }
        return result

    async def send_broadcast_command(self, action: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Sends command to ALL currently online clients simultaneously.
        """
        online_pcs = list(self.active_clients.keys())
        if not online_pcs:
            return {"status": "error", "message": "Немає підключених комп'ютерів."}

        tasks = [self.send_command(pc, action, params) for pc in online_pcs]
        await asyncio.gather(*tasks, return_exceptions=True)
        return {"status": "ok", "count": len(online_pcs), "pcs": online_pcs}

    async def send_command(self, pc_name: str, action: str, params: Optional[Dict[str, Any]] = None, timeout: float = 15.0) -> Dict[str, Any]:
        """
        Sends command to client and waits for response via correlation request_id.
        """
        websocket = self.active_clients.get(pc_name)
        if not websocket:
            return {"status": "error", "message": f"Комп'ютер '{pc_name}' не в мережі."}

        request_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self.pending_requests[request_id] = future

        message = {
            "request_id": request_id,
            "action": action,
            "params": params or {}
        }

        try:
            await websocket.send_text(json.dumps(message))
            response = await asyncio.wait_for(future, timeout=timeout)
            return response
        except asyncio.TimeoutError:
            return {"status": "error", "message": f"Таймаут очікування відповіді від '{pc_name}' ({timeout}с)"}
        except Exception as e:
            logger.error(f"Error sending command to {pc_name}: {e}")
            return {"status": "error", "message": str(e)}
        finally:
            self.pending_requests.pop(request_id, None)

    async def send_action(self, pc_name: str, action: str, params: Optional[Dict[str, Any]] = None) -> bool:
        """
        "Fire and forget" команда: надсилається без очікування відповіді.
        Використовується для частих подій (рух миші, скрол), де затримка критична.
        """
        websocket = self.active_clients.get(pc_name)
        if not websocket:
            return False
        try:
            await websocket.send_text(json.dumps({
                "request_id": None,
                "action": action,
                "params": params or {}
            }))
            return True
        except Exception as e:
            logger.error(f"Error sending action '{action}' to {pc_name}: {e}")
            return False

    def handle_client_response(self, data: Dict[str, Any]) -> bool:
        """Повертає True, якщо відповідь закрила чийсь запит на відповідь (request_id)."""
        request_id = data.get("request_id")
        if request_id and request_id in self.pending_requests:
            future = self.pending_requests[request_id]
            if not future.done():
                future.set_result(data)
            return True
        return False

    def update_client_stats(self, pc_name: str, stats: Dict[str, Any]):
        if pc_name in self.client_info:
            self.client_info[pc_name]["info"].update(stats)

    # Dashboard real-time connections
    async def connect_dashboard(self, websocket: WebSocket):
        await websocket.accept()
        self.dashboard_sockets.append(websocket)

    def disconnect_dashboard(self, websocket: WebSocket):
        if websocket in self.dashboard_sockets:
            self.dashboard_sockets.remove(websocket)

    async def broadcast_to_dashboards(self, data: Dict[str, Any]):
        message = json.dumps(data)
        for ws in list(self.dashboard_sockets):
            try:
                await ws.send_text(message)
            except Exception:
                self.disconnect_dashboard(ws)

manager = ConnectionManager()
