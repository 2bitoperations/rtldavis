import asyncio
import json
import logging
from typing import Set, Any

import websockets
from websockets.server import WebSocketServerProtocol

logger = logging.getLogger(__name__)


class DashboardWebSocketServer:
    def __init__(self, port: int):
        self.port = port
        self.clients: Set[WebSocketServerProtocol] = set()

    async def _handler(self, websocket: WebSocketServerProtocol, path: str):
        self.clients.add(websocket)
        logger.debug(f"WebSocket client connected. Total clients: {len(self.clients)}")
        try:
            # We don't expect messages from the dashboard, but we must pump the loop 
            # to handle ping/pong and detect disconnects natively.
            async for _ in websocket:
                pass
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.clients.remove(websocket)
            logger.debug(f"WebSocket client disconnected. Total clients: {len(self.clients)}")

    async def broadcast(self, event_type: str, payload: Any):
        """
        Thread-safe entry point to push JSON messages to all connected UI clients.
        """
        if not self.clients:
            return

        message = json.dumps({
            "type": event_type,
            "payload": payload
        })
        
        # websockets.broadcast natively ignores disconnected clients and doesn't throw.
        websockets.broadcast(self.clients, message)

    async def start(self):
        logger.warning(f"WebSocket server listening on 0.0.0.0:{self.port}")
        # Serve the websocket endpoint
        async with websockets.serve(self._handler, "0.0.0.0", self.port):
            await asyncio.Future()  # Run forever


def start_ws_server(port: int) -> DashboardWebSocketServer:
    server = DashboardWebSocketServer(port)
    asyncio.create_task(server.start())
    return server
