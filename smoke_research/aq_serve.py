"""
Preview the built page with this PC's air quality files before anything is published.

Serves web/index.html with the data base pointed at this server. Requests for the air quality files are answered from
regions/<region>/ (written by smoke_research/aq_check.py); every other data request is redirected to the live R2 URL
already baked into web/index.html by build_web.py. Nothing is uploaded.

Usage (from radar/):  python build_web.py; python smoke_research/aq_serve.py      then open http://127.0.0.1:8795/?r=pnw
"""
import http.server
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8795          # 8791 is taxes-web in BlackwaterLabs/.claude/launch.json
LOCAL = ("data/airquality.js", "frames/aq/", "data/values/aqi.js")

with open(os.path.join(ROOT, "web", "index.html"), encoding="utf-8") as f:
    PAGE = f.read()
R2 = re.search(r'<meta name="radar-base" content="([^"]+)">', PAGE).group(1)
PAGE = PAGE.replace('<meta name="radar-base" content="%s">' % R2, '<meta name="radar-base" content="http://127.0.0.1:%d/d/">' % PORT)


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=os.path.join(ROOT, "web"), **k)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            body = PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path.startswith("/d/"):
            reg, _, rest = path[3:].partition("/")
            local = os.path.join(ROOT, "regions", reg, *rest.split("/"))
            if rest.startswith(LOCAL) and os.path.isfile(local):
                with open(local, "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript" if local.endswith(".js") else "image/webp")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self.send_response(302)
            self.send_header("Location", R2 + path[3:] + ("?" + self.path.split("?", 1)[1] if "?" in self.path else ""))
            self.end_headers()
            return
        super().do_GET()


if __name__ == "__main__":
    print("serving on http://127.0.0.1:%d/?r=pnw (air quality files local, the rest from %s)" % (PORT, R2))
    http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
