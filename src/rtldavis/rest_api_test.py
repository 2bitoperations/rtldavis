import unittest
from unittest.mock import AsyncMock, MagicMock

from .rest_api import _handle


def _fake_reader(request_line: bytes) -> AsyncMock:
    reader = AsyncMock()
    # First readline() returns the request line, subsequent calls return the
    # blank line that ends the (empty) headers block.
    reader.readline.side_effect = [request_line, b"\r\n"]
    return reader


def _fake_writer() -> MagicMock:
    writer = MagicMock()
    writer.write = MagicMock()
    writer.drain = AsyncMock()
    writer.close = MagicMock()
    return writer


class TestRestApiRouting(unittest.IsolatedAsyncioTestCase):
    async def test_known_route_returns_200_and_body(self):
        reader = _fake_reader(b"GET /sensors HTTP/1.1\r\n")
        writer = _fake_writer()
        routes = {"/sensors": lambda: {"ok": True}}

        await _handle(reader, writer, routes)

        sent = b"".join(call.args[0] for call in writer.write.call_args_list)
        self.assertIn(b"200 OK", sent)
        self.assertIn(b'{"ok": true}', sent)

    async def test_second_route_dispatches_independently(self):
        reader = _fake_reader(b"GET /v1/current_conditions HTTP/1.1\r\n")
        writer = _fake_writer()
        sensors_handler = MagicMock(return_value={"should": "not be called"})
        routes = {
            "/sensors": sensors_handler,
            "/v1/current_conditions": lambda: {"data": None, "error": "stale"},
        }

        await _handle(reader, writer, routes)

        sensors_handler.assert_not_called()
        sent = b"".join(call.args[0] for call in writer.write.call_args_list)
        self.assertIn(b"200 OK", sent)
        self.assertIn(b"stale", sent)

    async def test_unregistered_path_returns_404(self):
        reader = _fake_reader(b"GET /nope HTTP/1.1\r\n")
        writer = _fake_writer()
        routes = {"/sensors": lambda: {}}

        await _handle(reader, writer, routes)

        sent = b"".join(call.args[0] for call in writer.write.call_args_list)
        self.assertIn(b"404 Not Found", sent)

    async def test_trailing_slash_normalizes_to_same_handler(self):
        reader = _fake_reader(b"GET /sensors/ HTTP/1.1\r\n")
        writer = _fake_writer()
        routes = {"/sensors": lambda: {"ok": True}}

        await _handle(reader, writer, routes)

        sent = b"".join(call.args[0] for call in writer.write.call_args_list)
        self.assertIn(b"200 OK", sent)

    async def test_non_get_method_returns_404(self):
        reader = _fake_reader(b"POST /sensors HTTP/1.1\r\n")
        writer = _fake_writer()
        handler = MagicMock(return_value={})
        routes = {"/sensors": handler}

        await _handle(reader, writer, routes)

        handler.assert_not_called()
        sent = b"".join(call.args[0] for call in writer.write.call_args_list)
        self.assertIn(b"404 Not Found", sent)


if __name__ == "__main__":
    unittest.main()
