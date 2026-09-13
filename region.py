"""
Region configuration. One capture engine, several focused windows.

Pick the active region with the REGION environment variable (default "pnw").
Every job module reads its map window and folders from here, so adding a region
is one entry in REGIONS plus, for the map, its home view.

Windows are 5x5 zoom-7 Web Mercator tiles (x0..x1, y0..y1); each is roughly
14 degrees of longitude by 9-11 degrees of latitude.
"""
import math
import os

ROOT = os.path.dirname(os.path.abspath(__file__))
Z = 7

REGIONS = {
    "pnw": {
        "name": "Pacific Northwest", "tiles": (19, 23, 42, 46),
        "home": [47.6, -120.7, 7], "focus": (46.5, 48.9, -122.1, -119.2),
        "states": ["WA", "OR", "ID", "MT"], "snotel_states": ["WA", "OR", "ID", "MT", "BC"],
        "cocorahs_states": ["WA"], "ndfd": "pacnwest",
        "asos": ["KEAT", "KSEA", "KPAE", "KYKM", "KELN", "KGEG", "KPUW", "KALW", "KPDT", "KMWH", "KEPH", "KOMK", "KBFI",
                 "KOLM", "KPDX", "KTTD", "KDLS", "KBLI", "KS52", "KAWO", "KRNT", "KTIW", "KHQM", "KSMP", "KCOE", "KLWS", "KBOI"],
    },
    "sierra": {
        "name": "Sierra & Nevada", "tiles": (19, 23, 47, 51),
        "home": [39.1, -120.0, 7], "focus": (38.0, 40.2, -121.5, -118.8),
        "states": ["CA", "NV", "OR"], "snotel_states": ["CA", "NV", "OR"],
        "cocorahs_states": ["CA", "NV"], "ndfd": "pacswest",
        "asos": ["KTVL", "KRNO", "KTRK", "KBLU", "KSAC", "KSMF", "KRDD", "KMFR", "KBIH", "KMMH", "KFAT", "KNLC", "KLOL", "KCXP", "KMEV"],
    },
    "utco": {
        "name": "Utah & Colorado", "tiles": (23, 27, 47, 51),
        "home": [39.1, -108.5, 7], "focus": (38.0, 40.2, -110.0, -106.5),
        "states": ["UT", "CO", "WY", "NM", "AZ"], "snotel_states": ["UT", "CO", "WY", "NM", "AZ"],
        "cocorahs_states": ["CO", "UT"], "ndfd": "crrocks",
        "asos": ["KGJT", "KASE", "KEGE", "KDEN", "KCOS", "KPUB", "KDRO", "KMTJ", "KSLC", "KPVU", "KVEL", "KCNY", "KHDN", "KLXV", "KTEX", "KGUC"],
    },
    "imw": {
        "name": "Idaho, Montana & Wyoming", "tiles": (22, 26, 43, 47),
        "home": [45.7, -111.0, 7], "focus": (44.5, 46.9, -112.5, -109.5),
        "states": ["ID", "MT", "WY"], "snotel_states": ["ID", "MT", "WY"],
        "cocorahs_states": ["MT", "ID", "WY"], "ndfd": "nrockies",
        "asos": ["KBZN", "KHLN", "KBTM", "KMSO", "KGTF", "KBIL", "KWYS", "KJAC", "KCOD", "KIDA", "KSUN", "KLVM", "KDLN", "KRIW", "KPIH"],
    },
}

KEY = os.environ.get("REGION", "pnw").lower()
if KEY not in REGIONS:
    raise SystemExit("unknown REGION %r; choose one of %s" % (KEY, ", ".join(REGIONS)))


def cfg():
    return REGIONS[KEY]


def window():
    """-> (Z, X0, X1, Y0, Y1)"""
    x0, x1, y0, y1 = cfg()["tiles"]
    return Z, x0, x1, y0, y1


def tile_lon(x):
    return x / 2 ** Z * 360.0 - 180.0


def tile_lat(y):
    return math.degrees(math.atan(math.sinh(math.pi - 2.0 * math.pi * y / 2 ** Z)))


def bbox():
    """-> (lat0, lat1, lon0, lon1) of the window"""
    _, x0, x1, y0, y1 = window()
    return tile_lat(y1 + 1), tile_lat(y0), tile_lon(x0), tile_lon(x1 + 1)


def bounds():
    """Leaflet-style [[S, W], [N, E]]"""
    lat0, lat1, lon0, lon1 = bbox()
    return [[lat0, lon0], [lat1, lon1]]


def region_dir():
    d = os.path.join(ROOT, "regions", KEY)
    os.makedirs(d, exist_ok=True)
    return d


def frames_dir():
    return os.path.join(region_dir(), "frames")


def data_dir():
    return os.path.join(region_dir(), "data")


def prefix():
    """R2 key prefix for this region, e.g. 'pnw/'"""
    return KEY + "/"
