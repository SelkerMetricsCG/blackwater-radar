"""
Build the snow-conditions site into web_snow/ for the Cloudflare Worker "snow"
(publish with `npx wrangler deploy --config wrangler_snow.toml`).

  web_snow/index.html   snow.html with the R2 public URL baked into its snow-base meta tag
  web_snow/terms.html   terms and privacy notice (a copy of terms.html)
  web_snow/favicon.ico  copied from web/ when present (with icon-192.png)
  web_snow/vendor/      Leaflet, copied from web/vendor/ when that folder exists (web/ is gitignored
                        and holds the only copies)

Usage:  python build_snow.py [--base URL] [--out DIR]
  --base   use this instead of R2_PUBLIC_URL from r2.env (local testing against a fake data tree)
  --out    write here instead of web_snow/
"""
import argparse
import os
import shutil

ROOT = os.path.dirname(os.path.abspath(__file__))
MARKER = '<meta name="snow-base" content="">'


def build(base=None, out=None, log=print):
    if not base:
        import r2sync
        env = r2sync.load_env() or {}
        base = env.get("R2_PUBLIC_URL", "")
        if not base:
            raise SystemExit("R2_PUBLIC_URL is not set in r2.env (or pass --base URL)")
    base = base.rstrip("/") + "/"
    out = out or os.path.join(ROOT, "web_snow")

    with open(os.path.join(ROOT, "snow.html"), encoding="utf-8") as f:
        html = f.read()
    if MARKER not in html:
        raise SystemExit("snow.html is missing the snow-base meta tag")
    html = html.replace(MARKER, '<meta name="snow-base" content="%s">' % base)

    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    shutil.copyfile(os.path.join(ROOT, "terms.html"), os.path.join(out, "terms.html"))
    for fn in ("favicon.ico", "icon-192.png"):          # web/ holds the only copies of the icons
        src = os.path.join(ROOT, "web", fn)
        if os.path.exists(src):
            shutil.copyfile(src, os.path.join(out, fn))
    vendor = os.path.join(ROOT, "web", "vendor")
    if os.path.isdir(vendor):
        shutil.copytree(vendor, os.path.join(out, "vendor"), dirs_exist_ok=True)
        log("copied web/vendor/ to %s/vendor/" % out)
    else:
        log("warning: web/vendor/ not found; %s/vendor/ was not written (the page needs vendor/leaflet.js and leaflet.css)" % out)
    log("built %s/index.html with base %s" % (out, base))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", help="data base URL (default: R2_PUBLIC_URL from r2.env)")
    ap.add_argument("--out", help="output directory (default: web_snow/)")
    a = ap.parse_args()
    build(a.base, a.out)
