"""
Minimal asyncio HTTP server exposing a read-only REST endpoint for sensor data.
"""
import asyncio
import json
import logging
from typing import Callable

logger = logging.getLogger(__name__)


async def _handle(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    get_data: Callable[[], dict],
) -> None:
    try:
        request_line = await reader.readline()
        # Consume remaining request headers
        while True:
            line = await reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break

        parts = request_line.decode(errors="replace").split()
        method = parts[0] if parts else ""
        path = parts[1] if len(parts) > 1 else ""

        if method == "GET" and path in ("/sensors", "/sensors/"):
            body = json.dumps(get_data(), indent=None)
            body_bytes = body.encode()
            status = "200 OK"
            content_type = "application/json"
        else:
            body_bytes = b"Not Found"
            status = "404 Not Found"
            content_type = "text/plain"

        response = (
            f"HTTP/1.1 {status}\r\n"
            f"Content-Type: {content_type}\r\n"
            f"Content-Length: {len(body_bytes)}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        ).encode() + body_bytes

        writer.write(response)
        await writer.drain()
    except Exception as exc:
        logger.debug(f"REST handler error: {exc}")
    finally:
        writer.close()


async def start_rest_server(port: int, get_data: Callable[[], dict]) -> None:
    """Start the HTTP server and log the listening address."""
    server = await asyncio.start_server(
        lambda r, w: _handle(r, w, get_data),
        host="0.0.0.0",
        port=port,
    )
    addrs = ", ".join(str(s.getsockname()) for s in server.sockets)
    logger.warning(f"REST API listening on {addrs} — GET /sensors")
    async with server:
        await server.serve_forever()
