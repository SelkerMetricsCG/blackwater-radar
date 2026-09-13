"""
Build the public site into web/ for upload to Cloudflare (the radar Worker).

  web/index.html        map.html with the R2 public URL baked in
  web/vendor/           Leaflet (already in place)
  web/data/             county outline and highways (copied from data/)

Usage:  python build_web.py
"""
import os
import shutil

import r2sync

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
html = html.replace(marker, '<meta name="radar-base" content="%s/">' % base)

with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as f:
    f.write(html)
shutil.rmtree(os.path.join(OUT, "data"), ignore_errors=True)   # all data is served from R2 now
print("built web/index.html with base", base)
