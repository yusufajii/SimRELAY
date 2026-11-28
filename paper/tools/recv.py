import base64, http.server, os, sys
OUT = sys.argv[1]
class H(http.server.BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()
    def do_POST(self):
        name = os.path.basename(self.path.strip("/")) or "out.bin"
        data = self.rfile.read(int(self.headers["Content-Length"]))
        if name.endswith(".png"):
            data = base64.b64decode(data.split(b",", 1)[-1])
        open(os.path.join(OUT, name), "wb").write(data)
        self.send_response(200); self._cors(); self.end_headers(); self.wfile.write(b"ok")
http.server.HTTPServer(("127.0.0.1", 8099), H).serve_forever()
