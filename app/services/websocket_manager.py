import json
import logging
import asyncio
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
        """Sends a JSON message instantaneously to all active websocket connections for a specific shop."""
        if shop_id in self.active_connections and self.active_connections[shop_id]:
            message_text = json.dumps(message, default=str)
            dead_connections = set()
            
            async def _send(ws: WebSocket):
                try:
                    await ws.send_text(message_text)
                except Exception as e:
                    logger.error(f"Failed to send WS message to shop {shop_id}: {str(e)}")
                    dead_connections.add(ws)

            # Broadcast concurrently to all sockets for 0 delay
            await asyncio.gather(*[_send(ws) for ws in list(self.active_connections[shop_id])], return_exceptions=True)
            
            # Cleanup dead connections
            for dead_conn in dead_connections:
                self.disconnect(shop_id, dead_conn)

manager = ConnectionManager()

class CustomerConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, Set[WebSocket]] = {}

    async def connect(self, customer_id: str, websocket: WebSocket):
        await websocket.accept()
        if customer_id not in self.active_connections:
            self.active_connections[customer_id] = set()
        self.active_connections[customer_id].add(websocket)
        logger.info(f"Customer WebSocket connected for ID: {customer_id}. Total active: {len(self.active_connections[customer_id])}")

    def disconnect(self, customer_id: str, websocket: WebSocket):
        if customer_id in self.active_connections:
            if websocket in self.active_connections[customer_id]:
                self.active_connections[customer_id].remove(websocket)
            if not self.active_connections[customer_id]:
                del self.active_connections[customer_id]
        logger.info(f"Customer WebSocket disconnected for ID: {customer_id}")

    async def broadcast_to_customer(self, customer_id: str, message: dict):
        """Broadcasts real-time order update instantaneously to customer socket."""
        if customer_id in self.active_connections and self.active_connections[customer_id]:
            message_text = json.dumps(message, default=str)
            dead_connections = set()

            async def _send(ws: WebSocket):
                try:
                    await ws.send_text(message_text)
                except Exception as e:
                    logger.error(f"Failed to send customer WS message for {customer_id}: {str(e)}")
                    dead_connections.add(ws)

            await asyncio.gather(*[_send(ws) for ws in list(self.active_connections[customer_id])], return_exceptions=True)
            
            for dead_conn in dead_connections:
                self.disconnect(customer_id, dead_conn)

customer_manager = CustomerConnectionManager()
