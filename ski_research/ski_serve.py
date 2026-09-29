"""
Preview the map with this checkout's map.html and this PC's ski files before anything is published.

Bakes map.html the way build_web.py does (region table; data base pointed at this server), serves the static assets
(Leaflet, icons, stf.js) from the main checkout's web/ folder, answers data/ski.js from regions/<region>/data/
(written by `REGION=<r> python ski.py`) and redirects every other data request to the live R2 bucket. Nothing is uploaded.

Usage (from the checkout):  python ski.py; python ski_research/ski_serve.py      then open http://127.0.0.1:8798/?r=pnw
"""
import http.server
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import region  # noqa: E402

PORT = 8798          # 8795 aq_serve, 8796 fires_serve, 8797 smoke_serve
R2 = "https://radar-files.blackwaterlabs.org/"
WEB = r"C:\Users\16035\Desktop\BlackwaterLabs\radar\web"      # the only copy of vendor/leaflet and the icons
LOCAL = ("data/ski.js",)

with open(os.path.join(ROOT, "map.html"), encoding="utf-8") as f:
    PAGE = f.read()
regions = {}
for key, c in region.REGIONS.items():
    x0, x1, y0, y1 = c["tiles"]
    regions[key] = {"name": c["name"], "home": c["home"], "snotel": bool(c.get("snotel_states")),
                    "bounds": [[region.tile_lat(y1 + 1), region.tile_lon(x0)], [region.tile_lat(y0), region.tile_lon(x1 + 1)]]}
    if c.get("avy"):
        regions[key]["avy"] = c["avy"]
PAGE = PAGE.replace('<meta name="radar-base" content="">',
                    '<meta name="radar-base" content="http://127.0.0.1:%d/d/">\n<script>window.REGIONS = %s;</script>' % (PORT, json.dumps(regions)))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=WEB, **k)

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
                self.send_header("Content-Type", "application/javascript")
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
    print("serving on http://127.0.0.1:%d/?r=pnw (ski.js local, the rest from %s)" % (PORT, R2))
    http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
