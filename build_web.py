"""
Build the public site into web/ for the Cloudflare Worker (publish with `npx wrangler deploy`).

  web/index.html   map.html with the R2 public URL and the region table baked in

Usage:  python build_web.py
"""
import json
import os

import r2sync
import region

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "web")

env = r2sync.load_env() or {}
base = env.get("R2_PUBLIC_URL", "").rstrip("/")
if not base:
    raise SystemExit("R2_PUBLIC_URL is not set in r2.env")

with open(os.path.join(ROOT, "map.html"), encoding="utf-8") as f:
    html = f.read()
marker = '<meta name="radar-base" content="">'
if marker not in html:
    raise SystemExit("map.html is missing the radar-base meta tag")
regions = {}
for key, c in region.REGIONS.items():
    x0, x1, y0, y1 = c["tiles"]
    regions[key] = {"name": c["name"], "home": c["home"],
                    "bounds": [[region.tile_lat(y1 + 1), region.tile_lon(x0)], [region.tile_lat(y0), region.tile_lon(x1 + 1)]]}
html = html.replace(marker, '<meta name="radar-base" content="%s/">\n<script>window.REGIONS = %s;</script>' % (base, json.dumps(regions)))

os.makedirs(OUT, exist_ok=True)
with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as f:
    f.write(html)
print("built web/index.html with base", base, "and regions", ", ".join(regions))
