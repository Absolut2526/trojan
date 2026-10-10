import asyncio
import json
import logging
import uuid
from typing import Dict, Any, Optional
from fastapi import WebSocket

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        # pc_name -> WebSocket
        self.active_clients: Dict[str, WebSocket] = {}
        # pc_name -> dict with specs/last_seen/stats
        self.client_info: Dict[str, Dict[str, Any]] = {}
        # request_id -> asyncio.Future for command responses
        self.pending_requests: Dict[str, asyncio.Future] = {}
        # Web dashboard sockets
        self.dashboard_sockets: list[WebSocket] = []

    async def connect_client(self, pc_name: str, websocket: WebSocket, initial_info: Optional[Dict[str, Any]] = None):
        if pc_name in self.active_clients:
            old_ws = self.active_clients[pc_name]
            try:
                await old_ws.close()
            except Exception:
                pass
        await websocket.accept()
        self.active_clients[pc_name] = websocket
        self.client_info[pc_name] = {
            "name": pc_name,
            "status": "online",
            "info": initial_info or {},
            "connected_at": asyncio.get_event_loop().time()
        }
        logger.info(f"Client '{pc_name}' connected.")
        await self.broadcast_to_dashboards({"type": "pc_status_change", "pc": pc_name, "status": "online"})

    def disconnect_client(self, pc_name: str, websocket: Optional[WebSocket] = None):
        if pc_name in self.active_clients:
            if websocket is None or self.active_clients[pc_name] == websocket:
                del self.active_clients[pc_name]
                if pc_name in self.client_info:
                    self.client_info[pc_name]["status"] = "offline"
                logger.info(f"Client '{pc_name}' disconnected.")
                asyncio.create_task(
                    self.broadcast_to_dashboards({"type": "pc_status_change", "pc": pc_name, "status": "offline"})
                )

    def is_online(self, pc_name: str) -> bool:
        return pc_name in self.active_clients

    def get_all_pcs(self) -> Dict[str, Dict[str, Any]]:
        result = {}
        for name, data in self.client_info.items():
            result[name] = {
                "name": name,
                "status": "online" if name in self.active_clients else "offline",
                "info": data.get("info", {})
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

    def handle_client_response(self, data: Dict[str, Any]):
        request_id = data.get("request_id")
        if request_id and request_id in self.pending_requests:
            future = self.pending_requests[request_id]
            if not future.done():
                future.set_result(data)

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
