"""site_worker.js (Worker "radar"): elevation tiles from R2 on the page's origin, everything else from the assets.
Run under node with a stand-in R2 binding and assets; skipped where node is missing."""
import json
import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")

JS = r"""
import worker from %s;
const store = { 'pnw/dem/v1/14/2690/5700.png': 'PNGDATA' };
const env = {
  TILES: { get: async k => (k in store ? { body: store[k], httpEtag: '"e1"' } : null) },
  ASSETS: { fetch: async r => new Response('asset ' + new URL(r.url).pathname) },
};
const ctx = { waitUntil() {} };
const go = async (path, method) => { const r = await worker.fetch(new Request('https://radar.blackwaterlabs.org' + path, { method: method || 'GET' }), env, ctx);
  return [r.status, r.headers.get('content-type'), r.headers.get('cache-control'), await r.text()]; };
const out = [];
for (const [p, m] of [['/pnw/dem/v1/14/2690/5700.png'], ['/pnw/dem/v1/14/2690/5701.png'], ['/'], ['/pnw/dem/v1/../../r2.env'],
                      ['/pnw/slope/v1/14/1/1.png'], ['/pnw/dem/v1/14/2690/5700.png', 'POST']]) out.push(await go(p, m));
process.stdout.write(JSON.stringify(out));
"""


def test_routes():
    url = json.dumps("file:///" + os.path.join(ROOT, "site_worker.js").replace("\\", "/"))
    out = subprocess.run([NODE, "--input-type=module", "-e", JS % url], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    tile, missing, home, sneaky, slope, post = json.loads(out.stdout)
    assert tile == [200, "image/png", "public, max-age=31536000, immutable", "PNGDATA"]
    assert missing[0] == 404 and missing[2] == "public, max-age=300"
    assert home == [200, "text/plain;charset=UTF-8", None, "asset /"]
    assert sneaky[3].startswith("asset ") and slope[3].startswith("asset ") and post[3].startswith("asset ")
