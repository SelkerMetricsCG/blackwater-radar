// Worker "radar": the static map page (./web, served before this script runs) plus the sun & shade elevation
// tiles from the R2 bucket on the page's own origin. The page must read the tiles' pixel values in WebGL, and the
// bucket's public domain sends no CORS header, so they cannot come from radar-files.blackwaterlabs.org directly.
// Only /<region>/dem/v<n>/<z>/<x>/<y>.png is served from R2; anything else falls through to the assets.
const DEM = /^\/([a-z]+)\/dem\/v(\d+)\/(\d+)\/(\d+)\/(\d+)\.png$/;

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (!DEM.test(url.pathname) || (request.method !== 'GET' && request.method !== 'HEAD')) return env.ASSETS.fetch(request);
    const cache = typeof caches !== 'undefined' ? caches.default : null;
    const hit = cache && await cache.match(request);
    if (hit) return hit;
    const obj = await env.TILES.get(url.pathname.slice(1));
    const res = obj
      ? new Response(request.method === 'HEAD' ? null : obj.body, { headers: { 'content-type': 'image/png', 'cache-control': 'public, max-age=31536000, immutable', etag: obj.httpEtag } })
      : new Response('no tile', { status: 404, headers: { 'content-type': 'text/plain', 'cache-control': 'public, max-age=300' } });   // short: a tile uploaded later must not stay missing
    if (cache && request.method === 'GET') ctx.waitUntil(cache.put(request, res.clone()));
    return res;
  },
};
