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
const store = { 'pnw/dem/v1/14/2690/5700.png': 'PNGDATA', 'pnw/frames/currents/20261013_12z/h01.png': 'FLOWDATA', 'pnw/currents/20261013_12z/h01.png': 'WRONGKEY',
  'pnw/frames/swell/gfswave_t18z_20261015/s07.png': 'SWELLDATA', 'pnw/frames/nwps/nwps_sew_t12z_20261015/h03.png': 'NWPSDATA' };
const asked = [];
const env = {
  TILES: { get: async k => (asked.push(k), k in store ? { body: store[k], httpEtag: '"e1"' } : null) },
  ASSETS: { fetch: async r => new Response('asset ' + new URL(r.url).pathname) },
};
const ctx = { waitUntil() {} };
const go = async (path, method) => { const r = await worker.fetch(new Request('https://radar.blackwaterlabs.org' + path, { method: method || 'GET' }), env, ctx);
  return [r.status, r.headers.get('content-type'), r.headers.get('cache-control'), await r.text()]; };
const out = [];
for (const [p, m] of [['/pnw/dem/v1/14/2690/5700.png'], ['/pnw/dem/v1/14/2690/5701.png'], ['/'], ['/pnw/dem/v1/../../r2.env'],
                      ['/pnw/slope/v1/14/1/1.png'], ['/pnw/dem/v1/14/2690/5700.png', 'POST'],
                      ['/pnw/currents/20261013_12z/h01.png'], ['/pnw/currents/20261013_12z/h02.png'], ['/pnw/currents/20261013_12z/h01.png', 'HEAD'],
                      ['/pnw/currents/x/h1.png'], ['/pnw/currents/../h01.png'],
                      ['/pnw/swell/gfswave_t18z_20261015/s07.png'], ['/pnw/nwps/nwps_sew_t12z_20261015/h03.png'], ['/pnw/waves/x/h01.png']]) out.push(await go(p, m));
out.push(asked);
process.stdout.write(JSON.stringify(out));
"""


def test_routes():
    url = json.dumps("file:///" + os.path.join(ROOT, "site_worker.js").replace("\\", "/"))
    out = subprocess.run([NODE, "--input-type=module", "-e", JS % url], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    tile, missing, home, sneaky, slope, post, flow, flow_missing, flow_head, one_digit, dotdot, swell, nwps, bad_kind, asked = json.loads(out.stdout)
    assert tile == [200, "image/png", "public, max-age=31536000, immutable", "PNGDATA"]
    assert missing[0] == 404 and missing[2] == "public, max-age=300"
    assert home == [200, "text/plain;charset=UTF-8", None, "asset /"]
    assert sneaky[3].startswith("asset ") and slope[3].startswith("asset ") and post[3].startswith("asset ")
    assert flow == [200, "image/png", "public, max-age=31536000, immutable", "FLOWDATA"]
    assert flow_missing[0] == 404 and flow_missing[2] == "public, max-age=300"
    assert flow_head[:3] == [200, "image/png", "public, max-age=31536000, immutable"] and flow_head[3] == ""
    assert one_digit[3].startswith("asset ") and dotdot[3].startswith("asset ")
    assert swell == [200, "image/png", "public, max-age=31536000, immutable", "SWELLDATA"]
    assert nwps == [200, "image/png", "public, max-age=31536000, immutable", "NWPSDATA"]
    assert bad_kind[3].startswith("asset ")
    assert "pnw/frames/swell/gfswave_t18z_20261015/s07.png" in asked and "pnw/frames/nwps/nwps_sew_t12z_20261015/h03.png" in asked
    assert not any("waves" in k for k in asked)
    assert "pnw/frames/currents/20261013_12z/h01.png" in asked and "pnw/currents/20261013_12z/h01.png" not in asked
    assert not any("h1.png" in k or ".." in k for k in asked)
