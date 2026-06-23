import json
import logging
from typing import Dict, Set
from fastapi import WebSocket

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        # Map shop_id to a set of connected WebSockets
        self.active_connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, shop_id: str, websocket: WebSocket):
        await websocket.accept()
        if shop_id not in self.active_connections:
            self.active_connections[shop_id] = set()
        self.active_connections[shop_id].add(websocket)
        logger.info(f"WebSocket connected for shop {shop_id}. Total connections: {len(self.active_connections[shop_id])}")

    def disconnect(self, shop_id: str, websocket: WebSocket):
        if shop_id in self.active_connections:
            if websocket in self.active_connections[shop_id]:
                self.active_connections[shop_id].remove(websocket)
            if not self.active_connections[shop_id]:
                del self.active_connections[shop_id]
        logger.info(f"WebSocket disconnected for shop {shop_id}")

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast_to_shop(self, shop_id: str, message: dict):
        """Sends a JSON message to all active websocket connections for a specific shop."""
        if shop_id in self.active_connections:
            message_text = json.dumps(message)
            dead_connections = set()
            for connection in self.active_connections[shop_id]:
                try:
                    await connection.send_text(message_text)
                except Exception as e:
                    logger.error(f"Failed to send WS message to shop {shop_id}: {str(e)}")
                    dead_connections.add(connection)
            
            # Cleanup dead connections
            for dead_conn in dead_connections:
                self.disconnect(shop_id, dead_conn)

manager = ConnectionManager()
