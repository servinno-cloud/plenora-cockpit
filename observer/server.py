from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FIXTURES = Path("/fixtures")
ROUTES = {
    "/v1/database": "database.json",
    "/v1/mail": "mail.json",
    "/v1/services": "services.json",
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        filename = ROUTES.get(self.path)
        if not filename:
            self.send_error(404)
            return
        payload = (FIXTURES / filename).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        self.send_error(405)

    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST

    def log_message(self, format, *args):
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
