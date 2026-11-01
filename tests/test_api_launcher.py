"""Startup uses a reserved listener and never replaces an occupied service."""
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import errno
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import socket
from threading import Event, Thread
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import api_launcher as launcher


@contextmanager
def running_service(*, title=launcher.API_TITLE, healthy=True, malformed=False):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/openapi.json":
                body = b"not json" if malformed else json.dumps({"info": {"title": title}}).encode()
            else:
                body = json.dumps({"status": "healthy" if healthy else "unhealthy", "database": "connected"}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=lambda: server.serve_forever(poll_interval=0.02), daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


class ApiLauncherTests(unittest.TestCase):
    def setUp(self):
        self.output = io.StringIO()
        self.stdout = redirect_stdout(self.output)
        self.stderr = redirect_stderr(self.output)
        self.stdout.__enter__()
        self.stderr.__enter__()
        self.addCleanup(self.stderr.__exit__, None, None, None)
        self.addCleanup(self.stdout.__exit__, None, None, None)

    def settings(self, port=0):
        return SimpleNamespace(api_host="127.0.0.1", api_port=port, database=Mock())

    def test_healthy_existing_api_exits_successfully_without_new_database_startup(self):
        with running_service() as port, patch.object(launcher, "_serve") as serve:
            settings = self.settings(port)
            self.assertEqual(launcher.run_server(Mock(), settings), 0)
            settings.database.require_password.assert_not_called()
            serve.assert_not_called()
            self.assertEqual(launcher._read_json("127.0.0.1", port, "/health")["status"], "healthy")
        self.assertIn("already running and healthy", self.output.getvalue())

    def test_unhealthy_existing_api_is_preserved_and_reports_failure(self):
        with running_service(healthy=False) as port, patch.object(launcher, "_serve") as serve:
            settings = self.settings(port)
            self.assertEqual(launcher.run_server(Mock(), settings), 1)
            settings.database.require_password.assert_not_called()
            serve.assert_not_called()
            self.assertEqual(launcher._read_json("127.0.0.1", port, "/health")["status"], "unhealthy")

    def test_another_service_is_preserved_even_if_its_health_response_looks_similar(self):
        with running_service(title="Another API") as port, patch.object(launcher, "_serve") as serve:
            settings = self.settings(port)
            self.assertEqual(launcher.run_server(Mock(), settings), 1)
            settings.database.require_password.assert_not_called()
            serve.assert_not_called()
            self.assertEqual(launcher._read_json("127.0.0.1", port, "/openapi.json")["info"]["title"], "Another API")

    def test_malformed_service_description_does_not_start_a_second_server(self):
        with running_service(malformed=True) as port, patch.object(launcher, "_serve") as serve:
            settings = self.settings(port)
            self.assertEqual(launcher.run_server(Mock(), settings), 1)
            settings.database.require_password.assert_not_called()
            serve.assert_not_called()

    def test_non_conflict_bind_error_does_not_probe_or_open_database(self):
        settings = self.settings()
        with patch.object(launcher, "_reserve_listener", side_effect=OSError(errno.EADDRNOTAVAIL, "Unavailable address")), \
             patch.object(launcher, "_existing_api") as existing, patch.object(launcher, "_serve") as serve:
            self.assertEqual(launcher.run_server(Mock(), settings), 1)
        settings.database.require_password.assert_not_called()
        existing.assert_not_called()
        serve.assert_not_called()

    def test_listener_is_reserved_before_credentials_and_closed_after_serving(self):
        settings = self.settings()
        reserved = []
        reserve = launcher._reserve_listener

        def capture(host, port):
            listener = reserve(host, port)
            reserved.append(listener)
            return listener

        def require_password():
            self.assertEqual(len(reserved), 1)
            with socket.socket() as contender:
                with self.assertRaises(OSError):
                    contender.bind(reserved[0].getsockname())

        settings.database.require_password.side_effect = require_password
        with patch.object(launcher, "_reserve_listener", side_effect=capture), \
             patch.object(launcher, "_serve", return_value=0) as serve:
            self.assertEqual(launcher.run_server(Mock(), settings), 0)
        self.assertEqual(serve.call_args.args[2], reserved[0])
        self.assertEqual(reserved[0].fileno(), -1)

    def test_missing_password_or_server_failure_releases_reserved_socket(self):
        for stage in ("password", "server"):
            with self.subTest(stage=stage):
                settings = self.settings()
                listener = launcher._reserve_listener("127.0.0.1", 0)
                if stage == "password":
                    settings.database.require_password.side_effect = ValueError("Password missing")
                with patch.object(launcher, "_reserve_listener", return_value=listener), \
                     patch.object(launcher, "_serve", side_effect=ValueError("Server failed")) as serve:
                    with self.assertRaises(ValueError):
                        launcher.run_server(Mock(), settings)
                self.assertEqual(listener.fileno(), -1)
                if stage == "password":
                    serve.assert_not_called()

    def test_wildcard_addresses_use_loopback_for_client_messages(self):
        self.assertEqual(launcher._url("0.0.0.0", 8000), "http://127.0.0.1:8000")
        self.assertEqual(launcher._url("::", 8000), "http://[::1]:8000")

    def test_real_uvicorn_serves_and_releases_the_prebound_socket_without_database(self):
        import uvicorn
        servers, listeners, failures, results = [], [], [], []
        ready = Event()
        real_server = uvicorn.Server
        real_serve = launcher._serve

        async def app(scope, receive, send):
            if scope["type"] == "lifespan":
                while True:
                    message = await receive()
                    if message["type"] == "lifespan.startup":
                        await send({"type": "lifespan.startup.complete"})
                    elif message["type"] == "lifespan.shutdown":
                        await send({"type": "lifespan.shutdown.complete"})
                        break
            elif scope["type"] == "http":
                await send({"type": "http.response.start", "status": 200, "headers": []})
                await send({"type": "http.response.body", "body": b'{"served":true}'})
                servers[0].should_exit = True

        def make_server(config):
            server = real_server(config)
            servers.append(server)
            return server

        def serve(app, settings, listener):
            listeners.append(listener)
            ready.set()
            return real_serve(app, settings, listener)

        def run():
            try:
                results.append(launcher.run_server(app, self.settings()))
            except BaseException as exc:
                failures.append(exc)

        with patch.object(launcher, "_serve", side_effect=serve), patch.object(uvicorn, "Server", side_effect=make_server):
            worker = Thread(target=run, daemon=True)
            worker.start()
            try:
                self.assertTrue(ready.wait(3))
                self.assertEqual(launcher._read_json("127.0.0.1", listeners[0].getsockname()[1], "/"), {"served": True})
            finally:
                for server in servers:
                    server.should_exit = True
                worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(results, [0])
        self.assertEqual(listeners[0].fileno(), -1)
