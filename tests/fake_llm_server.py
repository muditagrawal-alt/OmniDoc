"""
A tiny OpenAI-compatible server for tests: /chat/completions (plain and streamed) and
/embeddings. Behaviour per instance: always rate-limited, failing its first requests with
a server error, rejecting optional request fields, or answering with a fixed reply
(optionally wrapped in a <think> block).
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakeLLM:
    def __init__(self, reply: str = "Hello [1].", rate_limited: bool = False, reject_extras: bool = False,
                 think: bool = False, fail_first: int = 0):
        self.reply = reply
        self.rate_limited = rate_limited
        self.fail_first = fail_first
        self.reject_extras = reject_extras
        self.think = think
        self.requests = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, status, payload, headers=None):
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                owner.requests.append({"path": self.path, "body": body})
                if owner.fail_first > 0:
                    owner.fail_first -= 1
                    return self._send(503, {"error": {"message": "overloaded"}})
                if owner.rate_limited:
                    return self._send(429, {"error": {"message": "Rate limit reached for requests per minute"}}, {"retry-after": "7"})
                if owner.reject_extras and ("reasoning_effort" in body or "stream_options" in body
                                            or (body.get("response_format") or {}).get("type") == "json_schema"):
                    return self._send(400, {"error": {"message": "unsupported parameter"}})
                if self.path.endswith("/embeddings"):
                    data = [{"index": i, "embedding": [float(len(t) % 7), 1.0, 0.5]} for i, t in enumerate(body["input"])]
                    return self._send(200, {"data": data})
                text = ("<think>secret reasoning</think>" if owner.think else "") + owner.reply
                if body.get("stream"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    for i in range(0, len(text), 5):
                        chunk = {"choices": [{"delta": {"content": text[i:i + 5]}}]}
                        self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                    self.wfile.write(b'data: {"choices": [], "usage": {"prompt_tokens": 11, "completion_tokens": 7}}\n\n')
                    self.wfile.write(b"data: [DONE]\n\n")
                    return
                return self._send(200, {"choices": [{"message": {"content": text}}],
                                        "usage": {"prompt_tokens": 11, "completion_tokens": 7}})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
