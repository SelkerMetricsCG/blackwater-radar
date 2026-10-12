"""snow_worker.js (Worker "snow"): the class PNG and elevation tiles from R2 on the page's origin, everything else from
the assets. Run under node with a stand-in R2 binding and assets; skipped where node is missing."""
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
const store = { 'pnw/snow/state/2026-10-10_cls.png': 'CLS', 'pnw/snow/state/latest_cls.png': 'LATEST', 'pnw/dem/v1/13/1342/2850.png': 'DEM' };
const env = {
  BUCKET: { get: async k => (k in store ? { body: store[k], httpEtag: '"e1"' } : null) },
  ASSETS: { fetch: async r => new Response('asset ' + new URL(r.url).pathname) },
};
const ctx = { waitUntil() {} };
const go = async (path, method) => { const r = await worker.fetch(new Request('https://snow.blackwaterlabs.org' + path, { method: method || 'GET' }), env, ctx);
  return [r.status, r.headers.get('content-type'), r.headers.get('cache-control'), await r.text()]; };
const out = [];
for (const [p, m] of [['/r2/pnw/snow/state/2026-10-10_cls.png?v=5'], ['/r2/pnw/snow/state/latest_cls.png?t=1'], ['/r2/pnw/dem/v1/13/1342/2850.png'],
                      ['/r2/pnw/snow/state/2026-10-09_cls.png'], ['/'], ['/r2/pnw/snow/state/../../r2.env'], ['/r2/pnw/snow/archive/2026-10-10/daily.json.gz'],
                      ['/r2/pnw/dem/v1/13/1342/2850.png', 'POST']]) out.push(await go(p, m));
process.stdout.write(JSON.stringify(out));
"""


def test_routes():
    url = json.dumps("file:///" + os.path.join(ROOT, "snow_worker.js").replace("\\", "/"))
    out = subprocess.run([NODE, "--input-type=module", "-e", JS % url], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    cls, latest, dem, missing, home, sneaky, archive, post = json.loads(out.stdout)
    assert cls == [200, "image/png", "public, max-age=31536000, immutable", "CLS"]
    assert latest == [200, "image/png", "no-cache", "LATEST"]
    assert dem == [200, "image/png", "public, max-age=31536000, immutable", "DEM"]
    assert missing[0] == 404 and missing[2] == "public, max-age=300"
    assert home == [200, "text/plain;charset=UTF-8", None, "asset /"]
    assert sneaky[3].startswith("asset ") and archive[3].startswith("asset ") and post[3].startswith("asset ")
