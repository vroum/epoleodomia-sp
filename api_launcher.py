"""Reserve the API listener before startup and recognize an existing healthy API."""
import errno
import http.client
import json
import socket
import sys


API_TITLE = "Epoleodomia GIS API"


def _client_host(host):
    return {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(host, host)


def _url(host, port):
    host = _client_host(host)
    if ":" in host:
        host = "[" + host + "]"
    return f"http://{host}:{port}"


def _read_json(host, port, path):
    connection = http.client.HTTPConnection(_client_host(host), port, timeout=2)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        if response.status != 200:
            return None
        body = response.read(1024 * 1024 + 1)
        if len(body) > 1024 * 1024:
            return None
        return json.loads(body)
    except (OSError, ValueError, http.client.HTTPException):
        return None
    finally:
        connection.close()


def _existing_api(host, port):
    description = _read_json(host, port, "/openapi.json")
    if (not isinstance(description, dict) or
        not isinstance(description.get("info"), dict) or
        description["info"].get("title") != API_TITLE):
        return "unknown"
    health = _read_json(host, port, "/health")
    if isinstance(health, dict) and health.get("status") == "healthy" and health.get("database") == "connected":
        return "healthy"
    return "unhealthy"


def _reserve_listener(host, port):
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    listener = socket.socket(family, socket.SOCK_STREAM)
    try:
        # Windows REUSEADDR can admit a second bind to another process's port.
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((host, port))
        listener.listen(2048)
        listener.setblocking(False)
        return listener
    except BaseException:
        listener.close()
        raise


def _serve(app, settings, listener):
    import uvicorn
    server = uvicorn.Server(uvicorn.Config(app, host=settings.api_host, port=settings.api_port))
    print("Starting API at " + _url(settings.api_host, settings.api_port), flush=True)
    server.run(sockets=[listener])
    return 0 if server.started else 1


def run_server(app, settings):
    host, port = settings.api_host, settings.api_port
    try:
        listener = _reserve_listener(host, port)
    except OSError as exc:
        # An exclusive Windows listener may report WSAEACCES instead of INUSE.
        if exc.errno in (errno.EADDRINUSE, errno.EACCES) or getattr(exc, "winerror", None) in (10048, 10013):
            state = _existing_api(host, port)
            if state == "healthy":
                print("API is already running and healthy at " + _url(host, port))
                print("Continue in AutoCAD; this launcher can be closed.")
                return 0
            if state == "unhealthy":
                print("The API is already running, but its database health check failed. Restart its server process.", file=sys.stderr)
            else:
                print(f"Cannot use API port {port}: it is occupied or unavailable. Check its listener or choose another configured port.", file=sys.stderr)
        else:
            print(f"Cannot listen on {host}:{port}: {exc}", file=sys.stderr)
        return 1
    try:
        settings.database.require_password()
        return _serve(app, settings, listener)
    finally:
        listener.close()
