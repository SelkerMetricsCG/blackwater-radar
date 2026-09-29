@echo off
REM Build and publish the snow site (snow.blackwaterlabs.org). Run from the radar folder on Chris's PC.
REM Needs: r2.env (R2_PUBLIC_URL), Node on PATH, `npx wrangler login` done once, web\vendor\ present (Leaflet).
REM The custom domain is attached in the Cloudflare dashboard: Workers & Pages > snow > Settings > Domains & Routes.
git pull || exit /b 1
python build_snow.py || exit /b 1
npx wrangler deploy --config wrangler_snow.toml || exit /b 1
echo.
echo Deployed. First time only: attach snow.blackwaterlabs.org to the "snow" Worker in the Cloudflare dashboard.
