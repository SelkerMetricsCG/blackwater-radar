// Worker "radar-cron": starts the radar repo's GitHub Actions on time.
// GitHub's own schedule for capture.yml ("*/15") fired only every 2-6 h (40 runs 2026-09-20..26), so each
// Cloudflare cron below sends a workflow_dispatch instead. The GitHub schedules stay on as a backstop.
// Secret GH_TOKEN: fine-grained token "radar-cron", repository SelkerMetricsCG/blackwater-radar only, Actions: read and
// write, made 2026-09-27 to expire 2027-09-27. Renew: regenerate it at github.com/settings/personal-access-tokens, then
// here run `npx wrangler secret put GH_TOKEN` and paste it. If it lapses, capture.yml's watchdog step fails (email).
const REPO = 'SelkerMetricsCG/blackwater-radar';
const WORKFLOW = { '*/15 * * * *': 'capture.yml', '4 * * * *': 'hourly.yml', '20 9 * * *': 'snow.yml' };   // keys must match wrangler.toml crons

export default {
  async scheduled(event, env) {
    const wf = WORKFLOW[event.cron];
    if (!wf) throw new Error('no workflow for cron ' + event.cron);
    const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${wf}/dispatches`, {
      method: 'POST',
      headers: {
        Authorization: 'Bearer ' + env.GH_TOKEN,
        Accept: 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'blackwater-radar-cron',
      },
      body: JSON.stringify({ ref: 'main' }),
    });
    // 204 = queued; anything else (expired token, 404) shows as a failed invocation in the Worker's logs
    if (r.status !== 204) throw new Error(`${wf}: GitHub answered ${r.status} ${(await r.text()).slice(0, 300)}`);
  },
};
