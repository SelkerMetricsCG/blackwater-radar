"""
Finds each ski area's snow-report page so link-out markers open the report, not the home page (Chris, 2026-09-28).

For every area in ski_areas.json with a website and no hand-set report link, fetches the home page once, picks the
link whose address or text says snow report / conditions / mountain report, checks that it answers, and writes
ski_research/reports.json {id: url}. build_ski_areas.py merges it (a hand override wins). Vail-owned sites refuse
scripts, so those get the address every Vail resort uses, unfetched.

Run from a PC (not by any job):  python ski_research/find_reports.py            # only areas not yet in reports.json
                                 python ski_research/find_reports.py --all      # redo every area
"""
import concurrent.futures as cf
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LIST = os.path.join(ROOT, "ski_areas.json")
OUT = os.path.join(HERE, "reports.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
TIMEOUT = 15
WORKERS = 8
VAIL = ("stevenspass.com", "whistlerblackcomb.com", "skiheavenly.com", "kirkwood.com", "northstarcalifornia.com",
        "parkcitymountain.com", "vail.com", "breckenridge.com", "keystoneresort.com", "beavercreek.com", "skicb.com",
        "stowe.com", "okemo.com", "mountsnow.com", "huntermtn.com", "attitash.com", "skiwildcat.com", "mountsunapee.com",
        "crotchedmtn.com", "jfbb.com", "libertymountainresort.com", "skiroundtop.com", "skiwhitetail.com",
        "7springs.com", "hiddenvalleyresort.com", "laurelmountainski.com", "skiheavenly.com")
VAIL_PATH = "/the-mountain/mountain-conditions/snow-and-weather-report.aspx"
# what a report link looks like, best first
WORDS = [(r"snow[-_ ]?report", 6), (r"snow[-_ ]?conditions", 6), (r"mountain[-_ ]?report", 6), (r"conditions[-_ ]?report", 6),
         (r"daily[-_ ]?report", 5), (r"snow[-_ ]?and[-_ ]?weather", 5), (r"mountain[-_ ]?conditions", 5),
         (r"\bconditions\b", 4), (r"snow[-_ ]?stake", 3), (r"\bsnow\b", 2), (r"\bweather\b", 2), (r"\breport\b", 2)]
SKIP = re.compile(r"(mailto:|tel:|javascript:|\.(pdf|jpg|png)$|facebook|twitter|instagram|youtube|#)", re.I)
A_RE = re.compile(r"<a\b[^>]*?href\s*=\s*[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", re.I | re.S)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.geturl(), r.read(600_000).decode("utf-8", "ignore")


def host(url):
    return (urllib.parse.urlsplit(url).hostname or "").lower().removeprefix("www.")


def candidates(base, page):
    out = {}
    for href, text in A_RE.findall(page):
        href = html.unescape(href.strip())
        if SKIP.search(href):
            continue
        url = urllib.parse.urljoin(base, href).split("#")[0]
        if host(url) != host(base):
            continue
        text = re.sub(r"<[^>]+>", " ", html.unescape(text))
        text = re.sub(r"\s+", " ", text).strip().lower()
        path = urllib.parse.urlsplit(url).path.lower()
        score = 0
        for pat, w in WORDS:
            if re.search(pat, path):
                score = max(score, w + 1)
            if re.search(pat, text):
                score = max(score, w)
        if re.search(r"(webcam|cams?\b|lift[-_ ]?status|trail[-_ ]?report|forecast|blog|news|history|archive|summer|bike)", path + " " + text):
            score -= 3
        if score > 0:
            out[url] = max(score, out.get(url, 0))
    return sorted(out.items(), key=lambda kv: (-kv[1], len(kv[0])))


def find(area):
    web = area.get("web")
    if not web:
        return area["id"], None, "no website"
    if host(web) in VAIL or host(web).endswith(tuple("." + v for v in VAIL)):
        return area["id"], "https://www." + host(web) + VAIL_PATH, "vail pattern"
    try:
        final, page = fetch(web)
    except Exception as e:  # noqa: BLE001
        return area["id"], None, "home page: %r" % (e,)
    for url, score in candidates(final, page)[:3]:
        if url.rstrip("/") == final.rstrip("/"):
            continue
        try:
            got, _ = fetch(url)
        except Exception:  # noqa: BLE001
            continue
        return area["id"], got, "score %d" % score
    return area["id"], None, "no report link on the home page"


def main():
    with open(LIST, encoding="utf-8") as f:
        areas = json.load(f)
    found = {}
    if os.path.exists(OUT) and "--all" not in sys.argv:
        with open(OUT, encoding="utf-8") as f:
            found = json.load(f)
    todo = [a for a in areas if a.get("mp") is None and "report" not in a and a["id"] not in found]
    print("%d areas to look at (%d already known)" % (len(todo), len(found)))
    misses = []
    with cf.ThreadPoolExecutor(WORKERS) as ex:
        for aid, url, how in ex.map(find, todo):
            name = next(a["name"] for a in areas if a["id"] == aid)
            if url:
                found[aid] = url
            else:
                misses.append("%s: %s" % (name, how))
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(dict(sorted(found.items())), f, indent=0, ensure_ascii=False)
        f.write("\n")
    os.makedirs(os.path.join(HERE, "work"), exist_ok=True)
    with open(os.path.join(HERE, "work", "reports_missing.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(misses) + "\n")
    print("reports.json: %d links; %d areas without one (ski_research/work/reports_missing.txt)" % (len(found), len(misses)))


if __name__ == "__main__":
    main()
