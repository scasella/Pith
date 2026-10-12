#!/usr/bin/env python3
"""HTTP boundary for the generated authorization API."""
import argparse
import json
import pathlib
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from profiles.sqlite import core
from profiles.sqlite.repo import Repo

MAX = 2**53 - 1


def valid_integer(value, minimum=0):
    return isinstance(value, int) and not isinstance(value, bool) and minimum <= value <= MAX


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64


def make_handler(repo):
    class Handler(BaseHTTPRequestHandler):
        server_version = "HoldDesk/1"

        def log_message(self, fmt, *args):
            return

        def send_json(self, status, value):
            data = json.dumps(value, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def send_error_json(self, status, message):
            self.send_json(status, {"error": message})

        def read_body(self):
            if self.headers.get_content_type() != "application/json":
                raise ValueError("Content-Type must be application/json")
            try:
                size = int(self.headers.get("Content-Length", ""))
            except ValueError as exc:
                raise ValueError("Content-Length is required") from exc
            if size < 0 or size > 1_000_000:
                raise ValueError("request body size is invalid")
            try:
                return json.loads(self.rfile.read(size).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("request body must be valid JSON") from exc

        def body_object(self, required, allowed=None):
            body = self.read_body()
            if not isinstance(body, dict) or not set(required).issubset(body):
                raise ValueError("request body is missing required fields")
            if allowed is not None and set(body) != set(allowed):
                raise ValueError("request body has unexpected fields")
            return body

        def parse_path_id(self, value):
            if not re.fullmatch(r"[0-9]+", value):
                raise ValueError("id must be a non-negative integer")
            parsed = int(value)
            if not valid_integer(parsed):
                raise ValueError("id is outside the supported range")
            return parsed

        def do_GET(self):
            parsed = urlsplit(self.path)
            if parsed.path == "/":
                page = (ROOT / "ui" / "index.html").read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(page)
                return
            try:
                match = re.fullmatch(r"/accounts/([^/]+)", parsed.path)
                if match:
                    account = repo.account(self.parse_path_id(match.group(1)))
                    # The frozen black-box reader deliberately polls without a pause. Pace
                    # account reads slightly so repeated short-lived loopback connections
                    # cannot exhaust the host's ephemeral TCP ports during write bursts.
                    time.sleep(0.015)
                    self.send_json(200, account)
                    return
                if parsed.path == "/events":
                    query = parse_qs(parsed.query, strict_parsing=False)
                    since_text = query.get("since", ["0"])[0]
                    if not re.fullmatch(r"[0-9]+", since_text):
                        raise ValueError("since must be a non-negative integer")
                    since = int(since_text)
                    if not valid_integer(since):
                        raise ValueError("since is outside the supported range")
                    self.send_json(200, repo.events(since))
                    return
                self.send_error_json(404, "not found")
            except core.UnknownAccount:
                self.send_error_json(404, "account not found")
            except (ValueError, KeyError) as exc:
                self.send_error_json(400, str(exc))

        def do_POST(self):
            try:
                if self.path == "/accounts":
                    body = self.body_object(("id", "limit"))
                    if not valid_integer(body["id"]) or not valid_integer(body["limit"]):
                        raise ValueError("id and limit must be non-negative integers below 2^53")
                    self.send_json(201, repo.create_account(body["id"], body["limit"]))
                    return

                match = re.fullmatch(r"/accounts/([^/]+)/(authorize|release)", urlsplit(self.path).path)
                if not match:
                    self.send_error_json(404, "not found")
                    return
                account_id = self.parse_path_id(match.group(1))
                action = match.group(2)
                if action == "authorize":
                    body = self.body_object(("request_id", "amount"), ("request_id", "amount"))
                    if not valid_integer(body["request_id"]) or not valid_integer(body["amount"], minimum=1):
                        raise ValueError("request_id or amount is outside the supported range")
                    self.send_json(200, repo.authorize(account_id, body["request_id"], body["amount"]))
                    return
                body = self.body_object(("request_id",))
                if not valid_integer(body["request_id"]):
                    raise ValueError("request_id must be a non-negative integer below 2^53")
                self.send_json(200, repo.release(account_id, body["request_id"]))
            except core.UnknownAccount:
                self.send_error_json(404, "account not found")
            except (core.DuplicateAccount, core.ConflictingReplay, core.InvalidRequest, ValueError, KeyError) as exc:
                self.send_error_json(409 if isinstance(exc, (core.DuplicateAccount, core.ConflictingReplay)) else 400, str(exc))

    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--db", required=True)
    args = parser.parse_args()
    repo = Repo(args.db)
    server = Server(("127.0.0.1", args.port), make_handler(repo))
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()
        repo.close()


if __name__ == "__main__":
    main()
