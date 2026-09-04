"""
WebSocket connection manager — keeps track of all connected clients and
broadcasts updates to all of them at once (e.g. "risk just changed in
Puri" or "new incident reported near you").
"""
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        """Sends a JSON message to every currently connected client."""
        dead_connections = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                dead_connections.append(connection)

        # Clean up any connections that dropped without a clean disconnect
        for dead in dead_connections:
            self.disconnect(dead)


# Single shared instance — imported wherever we need to broadcast
manager = ConnectionManager()