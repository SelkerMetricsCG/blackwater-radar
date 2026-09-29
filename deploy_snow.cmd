@echo off
REM Build and publish the snow site (snow.blackwaterlabs.org). Run from the radar folder on Chris's PC.
REM Needs: r2.env (R2_PUBLIC_URL), Node on PATH, `npx wrangler login` done once, web\vendor\ present (Leaflet).
REM The custom domain snow.blackwaterlabs.org is attached by the deploy (routes in wrangler_snow.toml).
git pull || exit /b 1
python build_snow.py || exit /b 1
npx wrangler deploy --config wrangler_snow.toml || exit /b 1
echo.
echo Deployed to https://snow.blackwaterlabs.org
