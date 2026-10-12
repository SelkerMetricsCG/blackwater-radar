// Worker "snow": the snow page (./web_snow, served before this script runs) plus, on the page's own origin, the R2
// files whose pixels the page reads: the day's surface-class PNG (/r2/<region>/snow/state/<file>.png) and the sun &
// shade elevation tiles (/r2/<region>/dem/v<n>/<z>/<x>/<y>.png) for the click readout. The bucket's public domain sends
// no CORS header, so a canvas cannot read them from there. Anything else falls through to the assets.
const R2 = /^\/r2\/([a-z]+)\/(snow\/state\/[0-9a-z_-]+\.png|dem\/v\d+\/\d+\/\d+\/\d+\.png)$/;

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const m = R2.exec(url.pathname);
    if (!m || (request.method !== 'GET' && request.method !== 'HEAD')) return env.ASSETS.fetch(request);
    const latest = /\/latest_/.test(m[2]);                      // latest_cls.png is rewritten daily: never cached
    const cache = !latest && typeof caches !== 'undefined' ? caches.default : null;
    const hit = cache && await cache.match(request);           // keyed by the full URL: a re-run day's ?v= is a new key
    if (hit) return hit;
    const obj = await env.BUCKET.get(m[1] + '/' + m[2]);
    const res = obj
      ? new Response(request.method === 'HEAD' ? null : obj.body, { headers: { 'content-type': 'image/png', etag: obj.httpEtag,
          'cache-control': latest ? 'no-cache' : 'public, max-age=31536000, immutable' } })
      : new Response('not found', { status: 404, headers: { 'content-type': 'text/plain', 'cache-control': 'public, max-age=300' } });
    if (cache && obj && request.method === 'GET') ctx.waitUntil(cache.put(request, res.clone()));
    return res;
  },
};
