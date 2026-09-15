"""
Daily pull of the Roaring Creek DOE telemetry from the Solinst SolSat portal
(solinstsat.com) into the private R2 bucket the Roaring Creek sites read.

The portal has no scheduled export, so this logs in the way a browser does
(ASP.NET WebForms: fetch the login page for its ViewState, post the form), then
posts the "Export to CSV" postback on the device detail page for the last
365 days. The response is the same CSV the portal's download button gives, the
format Recession_Scheduler/report.csv already uses:

    RID3367:
    Received,Baro ft,Level ft,Water Level ft,Water Temp F,Battery Voltage (volts),Min ft,Max ft,...
    14-Sep-26 8:00 AM, , ,0.78, ,4.17,0.74,0.80, , , , , ,

Writes solsat/telemetry.csv (verbatim), telemetry.json and telemetry.js
(parsed daily rows, newest last) and uploads them to R2_BUCKET (roaring-data).

Credentials: SOLSAT_USER and SOLSAT_PASS from the environment, or from
solsat.env beside this file (gitignored). Chris pastes these himself.

    python solsat.py                    # fetch + upload
    python solsat.py --no-upload        # fetch only
    python solsat.py --parse path.csv   # parse an existing export, no login
"""
import datetime as dt
import html
import http.cookiejar
import json
import os
import re
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "solsat")
ENV_FILE = os.path.join(ROOT, "solsat.env")
BASE = "https://www.solinstsat.com/"
DEVICE = {"lid": "2026214654702", "gid": "0", "name": "RID3367"}     # the DOE SolSat 5 unit
HOURS = 8760                                                       # export window (portal max)
UA = "BlackwaterLabs solsat pull (chris.gabrielli@gmail.com)"


def log(msg):
    print("%s  %s" % (dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg), flush=True)


def creds():
    user, pw = os.environ.get("SOLSAT_USER", ""), os.environ.get("SOLSAT_PASS", "")
    if (not user or not pw) and os.path.exists(ENV_FILE):
        with open(ENV_FILE, encoding="utf-8") as f:
            for line in f:
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.strip().split("=", 1)
                    v = v.strip().strip('"').strip("'")
                    if k.strip() == "SOLSAT_USER":
                        user = v
                    elif k.strip() == "SOLSAT_PASS":
                        pw = v
    if not user or not pw:
        raise SystemExit("set SOLSAT_USER and SOLSAT_PASS (environment or solsat.env)")
    return user, pw


def hidden_fields(page):
    """The ASP.NET hidden inputs a postback must echo (__VIEWSTATE etc.)."""
    fields = {}
    for m in re.finditer(r'<input[^>]+type="hidden"[^>]*>', page, re.I):
        tag = m.group(0)
        n = re.search(r'name="([^"]+)"', tag)
        v = re.search(r'value="([^"]*)"', tag)
        if n:
            fields[n.group(1)] = html.unescape(v.group(1)) if v else ""
    return fields


class Portal:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.op.addheaders = [("User-Agent", UA)]

    def get(self, path):
        with self.op.open(BASE + path, timeout=60) as r:
            return r.read().decode("utf-8", errors="replace")

    def post(self, path, fields):
        data = urllib.parse.urlencode(fields).encode()
        req = urllib.request.Request(BASE + path, data=data, headers={"Content-Type": "application/x-www-form-urlencoded", "Referer": BASE + path})
        with self.op.open(req, timeout=120) as r:
            return r.read().decode("utf-8", errors="replace"), r.geturl()

    def login(self, user, pw):
        page = self.get("")
        f = hidden_fields(page)
        f.update({"ctl00$cphBody$txtUsername": user, "ctl00$cphBody$txtPass": pw, "ctl00$cphBody$btnAuthenticate": "Login"})
        body, url = self.post("", f)
        if "txtPass" in body or "User Login" in body[:2000]:
            raise SystemExit("login failed (still on the login page)")
        return True

    def export_csv(self, lid, gid, hours):
        path = "Detail.aspx?lid=%s&gid=%s" % (lid, gid)
        page = self.get(path)
        f = hidden_fields(page)
        f["ctl00$cphBody$ddlReportTime"] = str(hours)
        f["__EVENTTARGET"] = "ctl00$cphBody$lnkSave"
        f["__EVENTARGUMENT"] = ""
        body, _ = self.post(path, f)
        if not body.lstrip().startswith(DEVICE["name"] + ":") and "Received," not in body[:400]:
            raise SystemExit("unexpected export response: " + body[:200].replace("\n", " "))
        return body


def parse(text):
    """Portal CSV -> list of {date, level_ft, min_ft, max_ft, battery_v, water_temp_f}, oldest first."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    hdr = next((i for i, ln in enumerate(lines) if ln.startswith("Received")), None)
    if hdr is None:
        return []
    cols = [c.strip() for c in lines[hdr].split(",")]
    idx = {c: i for i, c in enumerate(cols)}
    rows = {}
    for ln in lines[hdr + 1:]:
        parts = [p.strip() for p in ln.split(",")]
        if len(parts) < 4:
            continue
        try:
            when = dt.datetime.strptime(parts[0], "%d-%b-%y %I:%M %p")
        except ValueError:
            continue
        num = lambda c: _f(parts[idx[c]]) if c in idx and idx[c] < len(parts) else None
        lvl = num("Water Level ft")
        if lvl is None:
            continue
        ok = lambda v: v is not None and abs(v - lvl) <= 0.5 and v > 0     # portal writes garbage min/max now and then
        mn, mx = num("Min ft"), num("Max ft")
        rows[when.strftime("%Y-%m-%d")] = {"date": when.strftime("%Y-%m-%d"), "time": when.strftime("%H:%M"), "level_ft": lvl,
                                           "min_ft": mn if ok(mn) else None, "max_ft": mx if ok(mx) else None,
                                           "battery_v": num("Battery Voltage (volts)"), "water_temp_f": num("Water Temp F")}
    return [rows[k] for k in sorted(rows)]


def _f(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def write_outputs(text, rows):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "telemetry.csv"), "w", encoding="utf-8", newline="") as f:
        f.write(text)
    meta = {"device": DEVICE["name"], "fetched": dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"), "n": len(rows),
            "first": rows[0]["date"] if rows else None, "last": rows[-1]["date"] if rows else None,
            "columns": ["date", "level_ft", "min_ft", "max_ft", "battery_v", "water_temp_f"],
            "rows": [[r["date"], r["level_ft"], r["min_ft"], r["max_ft"], r["battery_v"], r["water_temp_f"]] for r in rows]}
    with open(os.path.join(OUT, "telemetry.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, separators=(",", ":"))
    with open(os.path.join(OUT, "telemetry.js"), "w", encoding="utf-8") as f:
        f.write("window.LIVE_TELEMETRY=%s;\n" % json.dumps(meta, separators=(",", ":")))
    return meta


def upload():
    import r2sync
    env = r2sync.load_env()
    if env is None:
        log("R2 not configured; skipping upload")
        return
    bucket = os.environ.get("SOLSAT_R2_BUCKET", "roaring-data")     # never the public radar bucket
    s3 = r2sync.client(env)
    for fn in ("telemetry.csv", "telemetry.json", "telemetry.js"):
        r2sync.put(s3, bucket, fn, os.path.join(OUT, fn), "private, max-age=300")
    log("uploaded 3 files to bucket %s" % bucket)


def main(argv):
    if "--parse" in argv:
        path = argv[argv.index("--parse") + 1]
        rows = parse(open(path, encoding="latin-1").read())
        log("%d rows, %s to %s; last %s" % (len(rows), rows[0]["date"] if rows else None, rows[-1]["date"] if rows else None, rows[-1] if rows else None))
        return
    user, pw = creds()
    p = Portal()
    p.login(user, pw)
    log("logged in")
    text = p.export_csv(DEVICE["lid"], DEVICE["gid"], HOURS)
    rows = parse(text)
    if not rows:
        raise SystemExit("export parsed to zero rows")
    meta = write_outputs(text, rows)
    log("%d daily rows, %s to %s, last level %.2f ft, battery %s V" % (meta["n"], meta["first"], meta["last"], rows[-1]["level_ft"], rows[-1]["battery_v"]))
    if "--no-upload" not in argv:
        upload()


if __name__ == "__main__":
    main(sys.argv[1:])
