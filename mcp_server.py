"""An MCP server inside VL, so Claude (or another MCP client) can work on the
graph that is open in the window.

Transport: MCP "Streamable HTTP" in its simplest form. The client POSTs one
JSON-RPC message to http://127.0.0.1:<port>/mcp and gets the answer as a
JSON response; there are no server-sent events and no sessions. It runs on
Qt's event loop (QTcpServer), so tools touch the GraphModel on the GUI
thread like the UI does; nothing needs locking.

Only connections from this computer are accepted, and requests with a
browser Origin or Host header other than localhost are refused, so a web
page can't drive VL (DNS rebinding).

Connect Claude Code with:
    claude mcp add --transport http vl http://127.0.0.1:7357/mcp
"""

import json
import sys
import traceback
from typing import Any
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, QSettings, Property, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtNetwork import QHostAddress, QTcpServer, QTcpSocket

from vl_tools import INSTRUCTIONS, Deferred, ToolError, ToolResult, VlTools

DEFAULT_PORT = 7357
PATH = "/mcp"
# Newest first. A client asking for one of these gets it; otherwise the newest.
PROTOCOL_VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26"]
MAX_HEADER_BYTES = 64 * 1024
MAX_BODY_BYTES = 16 * 1024 * 1024
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}

STATUS_TEXT = {200: "OK", 202: "Accepted", 400: "Bad Request", 403: "Forbidden", 404: "Not Found",
               405: "Method Not Allowed", 411: "Length Required", 413: "Payload Too Large",
               500: "Internal Server Error"}


def _jsonrpc_error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


class _Client:
    """One TCP connection: a buffer of unparsed bytes, handled one request at a time."""

    def __init__(self, socket: QTcpSocket):
        self.socket = socket
        self.buffer = b""
        self.busy = False      # Waiting for a deferred tool result.
        self.closed = False


class McpServer(QObject):
    stateChanged = Signal()
    # A client finished the MCP handshake: (client name).
    clientConnected = Signal(str)

    def __init__(self, tools: VlTools, version: str):
        super().__init__()
        self._tools = tools
        self._version = version
        self._settings = QSettings("VL", "VL")
        self._enabled = self._settings.value("mcp/enabled", False, type=bool)
        self._port = self._settings.value("mcp/port", DEFAULT_PORT, type=int)
        self._error = ""
        self._client_name = ""
        self._server: QTcpServer | None = None
        self._clients: list[_Client] = []
        self._apply()

    # -- Properties for QML ---------------------------------------------------

    @Property(bool, notify=stateChanged)
    def enabled(self) -> bool:
        return self._enabled

    @Property(int, notify=stateChanged)
    def port(self) -> int:
        return self._port

    @Property(bool, notify=stateChanged)
    def listening(self) -> bool:
        return self._server is not None

    @Property(str, notify=stateChanged)
    def error(self) -> str:
        return self._error

    @Property(str, notify=stateChanged)
    def url(self) -> str:
        return f"http://127.0.0.1:{self._port}{PATH}"

    @Property(str, notify=stateChanged)
    def addCommand(self) -> str:
        return f"claude mcp add --transport http vl {self.url}"

    @Property(str, notify=stateChanged)
    def clientName(self) -> str:
        """The last client that connected ("" if none yet)."""
        return self._client_name

    @Slot(bool)
    def setEnabled(self, enabled: bool):
        self._settings.setValue("mcp/enabled", enabled)
        if enabled != self._enabled:
            self._enabled = enabled
            self._apply()

    @Slot(int)
    def setPort(self, port: int):
        if not 1024 <= port <= 65535:
            self._error = "The port must be between 1024 and 65535."
            self.stateChanged.emit()
            return
        self._settings.setValue("mcp/port", port)
        if port != self._port:
            self._port = port
            self._apply()

    @Slot()
    def copyAddCommand(self):
        QGuiApplication.clipboard().setText(self.addCommand)

    def enable_for_session(self):
        """Start the server for this run only (--mcp), without changing the saved setting."""
        if not self._enabled:
            self._enabled = True
            self._apply()

    # -- Listening ------------------------------------------------------------

    def _apply(self):
        """Start or stop listening to match enabled/port."""
        if self._server is not None:
            self._server.close()
            self._server.deleteLater()
            self._server = None
            for client in list(self._clients):
                client.socket.abort()
        self._error = ""
        if self._enabled:
            server = QTcpServer(self)
            if server.listen(QHostAddress(QHostAddress.SpecialAddress.LocalHost), self._port):
                server.newConnection.connect(self._accept)
                self._server = server
            else:
                self._error = f"Could not listen on port {self._port}: {server.errorString()}"
                server.deleteLater()
        self.stateChanged.emit()

    def _accept(self):
        while self._server is not None and self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            client = _Client(socket)
            self._clients.append(client)
            socket.readyRead.connect(lambda c=client: self._read(c))
            socket.disconnected.connect(lambda c=client: self._drop(c))

    def _drop(self, client: _Client):
        client.closed = True
        if client in self._clients:
            self._clients.remove(client)
        client.socket.deleteLater()

    # -- HTTP -----------------------------------------------------------------

    def _read(self, client: _Client):
        client.buffer += bytes(client.socket.readAll())
        self._process(client)

    def _process(self, client: _Client):
        """Handle every complete request in the buffer, one at a time."""
        while not client.busy and not client.closed:
            head_end = client.buffer.find(b"\r\n\r\n")
            if head_end == -1:
                if len(client.buffer) > MAX_HEADER_BYTES:
                    self._respond(client, 413, b"", close=True)
                return
            try:
                head = client.buffer[:head_end].decode("latin-1")
                request_line, *header_lines = head.split("\r\n")
                method, target, _version = request_line.split(" ", 2)
                headers = {}
                for line in header_lines:
                    name, _, value = line.partition(":")
                    headers[name.strip().lower()] = value.strip()
            except ValueError:
                self._respond(client, 400, b"", close=True)
                return

            if "chunked" in headers.get("transfer-encoding", "").lower():
                self._respond(client, 411, b"", close=True)
                return
            try:
                length = int(headers.get("content-length", "0"))
            except ValueError:
                self._respond(client, 400, b"", close=True)
                return
            if length > MAX_BODY_BYTES:
                self._respond(client, 413, b"", close=True)
                return
            body_start = head_end + 4
            if len(client.buffer) < body_start + length:
                return  # Wait for the rest of the body.
            body = client.buffer[body_start:body_start + length]
            client.buffer = client.buffer[body_start + length:]
            close = headers.get("connection", "").lower() == "close"
            self._handle_http(client, method, target, headers, body, close)

    def _handle_http(self, client: _Client, method: str, target: str, headers: dict[str, str],
                     body: bytes, close: bool):
        if not self._local(headers):
            self._respond(client, 403, b"Only local clients may use VL's MCP server.", close, "text/plain")
            return
        if urlsplit(target).path.rstrip("/") != PATH:
            self._respond(client, 404, b"VL's MCP endpoint is " + PATH.encode(), close, "text/plain")
            return
        if method != "POST":
            # No server-to-client event stream and no sessions to delete.
            self._respond(client, 405, b"", close, extra={"Allow": "POST"})
            return

        try:
            message = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            self._respond_json(client, _jsonrpc_error(None, -32700, f"Parse error: {e}"), close, 400)
            return
        if not isinstance(message, dict):
            self._respond_json(client, _jsonrpc_error(None, -32600, "Expected a single JSON-RPC message."),
                               close, 400)
            return

        if "method" not in message or "id" not in message:
            # A notification, or a response to a request we never send.
            self._respond(client, 202, b"", close)
            return

        reply = self._handle_request(message)
        if isinstance(reply, Deferred):
            client.busy = True

            def done(response: dict[str, Any]):
                client.busy = False
                if not client.closed:
                    self._respond_json(client, response, close)
                    self._process(client)
            reply.then(lambda result: done(self._tool_response(message["id"], result)))
        else:
            self._respond_json(client, reply, close)

    @staticmethod
    def _local(headers: dict[str, str]) -> bool:
        host = headers.get("host", "")
        hostname = urlsplit("//" + host).hostname if host else None
        if hostname is not None and hostname not in LOCAL_HOSTS:
            return False
        origin = headers.get("origin")
        if origin and origin != "null":
            if urlsplit(origin).hostname not in LOCAL_HOSTS:
                return False
        return True

    def _respond_json(self, client: _Client, data: dict[str, Any], close: bool, status: int = 200):
        self._respond(client, status, json.dumps(data, ensure_ascii=False).encode("utf-8"), close,
                      "application/json")

    def _respond(self, client: _Client, status: int, body: bytes, close: bool,
                 content_type: str = "", extra: dict[str, str] | None = None):
        if client.closed:
            return
        lines = [f"HTTP/1.1 {status} {STATUS_TEXT.get(status, '')}",
                 f"Content-Length: {len(body)}",
                 f"Connection: {'close' if close else 'keep-alive'}"]
        if content_type:
            lines.append(f"Content-Type: {content_type}; charset=utf-8")
        lines += [f"{k}: {v}" for k, v in (extra or {}).items()]
        client.socket.write(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + body)
        if close:
            client.closed = True
            client.socket.disconnectFromHost()

    # -- JSON-RPC / MCP -------------------------------------------------------

    def _handle_request(self, message: dict[str, Any]) -> "dict[str, Any] | Deferred":
        msg_id, method = message["id"], message["method"]
        params = message.get("params") or {}

        if method == "initialize":
            requested = params.get("protocolVersion")
            info = params.get("clientInfo") or {}
            self._client_name = str(info.get("title") or info.get("name") or "An MCP client")
            self.stateChanged.emit()
            self.clientConnected.emit(self._client_name)
            return {"jsonrpc": "2.0", "id": msg_id, "result": {
                "protocolVersion": requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "vl", "title": "VL (Visual Language)", "version": self._version},
                "instructions": INSTRUCTIONS,
            }}

        if method == "ping":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": msg_id,
                    "result": {"tools": [t.definition() for t in self._tools.tools.values()]}}

        if method == "tools/call":
            tool = self._tools.tools.get(params.get("name"))
            if tool is None:
                return _jsonrpc_error(msg_id, -32602, f"Unknown tool: {params.get('name')}")
            arguments = params.get("arguments") or {}
            if not isinstance(arguments, dict):
                return _jsonrpc_error(msg_id, -32602, "Tool arguments must be an object.")
            try:
                result = tool.handler(arguments)
            except ToolError as e:
                result = ToolResult.text(str(e), is_error=True)
            except Exception as e:  # A bug in a tool must not take the app down.
                traceback.print_exc(file=sys.stderr)
                result = ToolResult.text(f"Internal error in VL ({type(e).__name__}: {e}). "
                                         "Nothing was changed by a failed edit_graph.", is_error=True)
            if isinstance(result, Deferred):
                return result
            return self._tool_response(msg_id, result)

        return _jsonrpc_error(msg_id, -32601, f"Method not found: {method}")

    @staticmethod
    def _tool_response(msg_id: Any, result: ToolResult) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": msg_id,
                "result": {"content": result.content, "isError": result.is_error}}
