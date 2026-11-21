#!/usr/bin/env python3
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Dynamic port for Render deployment
PORT    = int(os.environ.get("PORT", 8080))
TIMEOUT = 60
ROOT    = os.path.dirname(os.path.abspath(__file__))

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, status, ctype, body):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        # CORS Headers for Cloudflare Pages
        self.send_header("Access-Control-Allow-Origin", "*") 
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        # Handle CORS preflight requests
        self._send(200, "text/plain", "")

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        
        length = int(self.headers.get("Content-Length", "0"))
        code   = self.rfile.read(length).decode("utf-8", errors="replace")
        
        if path == "/lint":
            self.handle_lint(code)
        elif path == "/run":
            self.handle_run(code)
        else:
            self._send(404, "text/plain", "Not found")

    def handle_lint(self, code):
        tmpdir = tempfile.mkdtemp(prefix="gopilr-lint-")
        try:
            src = os.path.join(tmpdir, "main.go")
            with open(src, "w", encoding="utf-8") as f:
                f.write(code)
            
            # Use go vet to catch syntax and basic errors
            proc = subprocess.run(["go", "vet", "main.go"], cwd=tmpdir, capture_output=True, text=True, timeout=10)
            
            errors = []
            if proc.returncode != 0:
                for line in proc.stderr.split('\n'):
                    match = re.search(r'main\.go:(\d+):(\d+):\s*(.*)', line)
                    if match:
                        line_num = int(match.group(1)) - 1
                        col_num  = int(match.group(2)) - 1
                        message  = match.group(3)
                        errors.append({
                            "line": line_num,
                            "ch": col_num,
                            "message": message,
                            "severity": "error"
                        })
            self._send(200, "application/json", json.dumps(errors))
        except Exception:
            self._send(200, "application/json", "[]")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def handle_run(self, code):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Transfer-Encoding", "chunked")
        # CORS for streaming response
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        def chunk(data: bytes):
            self.wfile.write(b"%X\r\n" % len(data) + data + b"\r\n")
            self.wfile.flush()

        def end_chunks():
            try:
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except: pass

        tmpdir = tempfile.mkdtemp(prefix="gopilr-run-")
        proc = None
        try:
            with open(os.path.join(tmpdir, "main.go"), "w", encoding="utf-8") as f:
                f.write(code)

            proc = subprocess.Popen(
                ["go", "run", "main.go"],
                cwd=tmpdir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
            )

            timer = threading.Timer(TIMEOUT, lambda: proc.poll() is None and proc.kill())
            timer.start()

            fd = proc.stdout.fileno()
            try:
                while True:
                    data = os.read(fd, 4096)
                    if not data: break
                    chunk(data)
            except (BrokenPipeError, ConnectionResetError):
                try: proc.kill()
                except: pass
            finally:
                timer.cancel()
                try: proc.wait(timeout=5)
                except: pass
                end_chunks()
        except Exception as e:
            try: chunk(f"\n[server error] {e}\n".encode())
            except: pass
            try: end_chunks()
            except: pass
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def log_message(self, fmt, *args): 
        pass

def main():
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("=" * 52)
    print(f" GoPilr backend is running on port {PORT}")
    print("=" * 52)
    try: 
        server.serve_forever()
    except KeyboardInterrupt: 
        print("\nStopped.")

if __name__ == "__main__":
    main()
