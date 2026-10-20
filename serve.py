import os
import re
import sys
import mimetypes
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

ROOT = Path(__file__).resolve().parent

class AudioCORSRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def end_headers_with_cors(self, extra_headers=None):
        origin = self.headers.get("Origin")
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
        else:
            self.send_header("Access-Control-Allow-Origin", "*")

        self.send_header("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS, POST")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Expose-Headers", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")

        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, str(v))
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204, "No Content")
        self.end_headers_with_cors({
            "Content-Length": "0",
            "Access-Control-Max-Age": "86400"
        })

    def do_HEAD(self):
        self.handle_file(send_body=False)

    def do_GET(self):
        self.handle_file(send_body=True)

    def handle_file(self, send_body=True):
        clean_path = self.path.split("?")[0].lstrip("/")
        file_path = (ROOT / clean_path).resolve()

        # Security check
        try:
            file_path.relative_to(ROOT)
        except ValueError:
            self.send_error(403, "Forbidden")
            return

        if not file_path.is_file():
            self.send_error(404, "File Not Found")
            return

        file_size = file_path.stat().st_size
        mime_type, _ = mimetypes.guess_type(str(file_path))
        if not mime_type:
            mime_type = "audio/wav" if file_path.suffix.lower() == ".wav" else "application/octet-stream"

        range_header = self.headers.get("Range")
        if range_header:
            m = re.match(r"bytes=(\d+)-(\d*)", range_header)
            if m:
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else file_size - 1
                if start >= file_size:
                    self.send_response(416, "Requested Range Not Satisfiable")
                    self.end_headers_with_cors({"Content-Range": f"bytes */{file_size}"})
                    return

                end = min(end, file_size - 1)
                content_length = end - start + 1

                self.send_response(206, "Partial Content")
                self.end_headers_with_cors({
                    "Content-Type": mime_type,
                    "Content-Length": content_length,
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Accept-Ranges": "bytes"
                })

                if send_body:
                    with open(file_path, "rb") as f:
                        f.seek(start)
                        rem = content_length
                        while rem > 0:
                            buf = f.read(min(rem, 65536))
                            if not buf:
                                break
                            try:
                                self.wfile.write(buf)
                            except (BrokenPipeError, ConnectionResetError):
                                break
                            rem -= len(buf)
                return

        # Regular 200 OK
        self.send_response(200, "OK")
        self.end_headers_with_cors({
            "Content-Type": mime_type,
            "Content-Length": file_size,
            "Accept-Ranges": "bytes"
        })

        if send_body:
            with open(file_path, "rb") as f:
                while True:
                    buf = f.read(65536)
                    if not buf:
                        break
                    try:
                        self.wfile.write(buf)
                    except (BrokenPipeError, ConnectionResetError):
                        break

    def log_message(self, format, *args):
        # Clean logging
        sys.stderr.write(f"[{self.log_date_time_string()}] {self.address_string()} - {format % args}\n")
        sys.stderr.flush()

if __name__ == "__main__":
    port = 8001
    server_address = ("", port)
    httpd = ThreadingHTTPServer(server_address, AudioCORSRequestHandler)
    print(f"Serving audio files with wide-open CORS and Range support at http://localhost:{port}/")
    sys.stdout.flush()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.server_close()
