"""
Tests for solsat.py: parse(), _f(), write_outputs(), creds(), hidden_fields(),
Portal.login()/export_csv() against a stubbed transport, and main() with a
fake Portal. Nothing here opens a socket or reads solsat.env (see conftest).

tests/fixtures/solsat_export.csv mimics the portal's "Export to CSV" response
described in the solsat.py docstring: a "RID3367:" title line, the header row,
then one reading per line, 14 comma-separated fields with blanks as spaces.
The six columns after "Max ft" are left unnamed because the docstring elides
them. The fixture deliberately contains the cases parse() has to handle:

    01-Sep   in-air reading (about -1013 ft), dropped
    03-Sep   Min ft of 0.00, rejected (must be > 0)
    04-Sep   Min ft of 3.10, rejected (more than 0.5 ft from the level)
    05-Sep   blank Min/Max and blank temperature
    06-Sep   blank Water Level, dropped
    07-Sep   two readings on one day; the later line in the file wins
    "Sep 9"  unparseable date, skipped
    "short,row"  fewer than four fields, skipped
    14-Sep   the exact example row from the docstring
"""
import json
import math
import os
import re

import pytest

import solsat

HEADER = ("RID3367:\n"
          "Received,Baro ft,Level ft,Water Level ft,Water Temp F,Battery Voltage (volts),Min ft,Max ft,,,,,,\n")


def row(date, level, mn="", mx="", batt="4.17", temp=""):
    return "%s, , ,%s,%s,%s,%s,%s, , , , , ,\n" % (date, level, temp, batt, mn, mx)


# ----------------------------------------------------------------------------- _f


@pytest.mark.parametrize("s, expected", [
    ("0.78", 0.78),
    ("4.17", 4.17),
    ("-1013.42", -1013.42),
    (" 0.5 ", 0.5),          # float() tolerates surrounding whitespace
    ("1e3", 1000.0),
    ("0", 0.0),
    (7, 7.0),                # already numeric
])
def test_f_parses_numbers(s, expected):
    assert solsat._f(s) == expected


@pytest.mark.parametrize("s", ["", " ", "abc", "0.78 ft", None, "1,000", "--", [1.0]])
def test_f_returns_none_for_junk(s):
    assert solsat._f(s) is None


def test_f_passes_nan_and_inf_through():
    # float() accepts these spellings; parse() drops them later via the 0..10 ft range check.
    assert math.isnan(solsat._f("nan"))
    assert solsat._f("inf") == math.inf


# -------------------------------------------------------------------------- parse


def test_parse_fixture_row_count_and_order(export_text):
    rows = solsat.parse(export_text)
    assert [r["date"] for r in rows] == ["2026-09-02", "2026-09-03", "2026-09-04", "2026-09-05", "2026-09-07",
                                         "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-14"]


def test_parse_docstring_example_row(export_text):
    last = solsat.parse(export_text)[-1]
    assert last == {"date": "2026-09-14", "time": "08:00", "level_ft": 0.78, "min_ft": 0.74, "max_ft": 0.80,
                    "battery_v": 4.17, "water_temp_f": None}


def test_parse_row_shape(export_text):
    for r in solsat.parse(export_text):
        assert set(r) == {"date", "time", "level_ft", "min_ft", "max_ft", "battery_v", "water_temp_f"}
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", r["date"])
        assert re.fullmatch(r"\d{2}:\d{2}", r["time"])
        assert isinstance(r["level_ft"], float)


def test_parse_full_row_with_temperature(export_text):
    first = solsat.parse(export_text)[0]
    assert first == {"date": "2026-09-02", "time": "08:00", "level_ft": 0.91, "min_ft": 0.88, "max_ft": 0.95,
                     "battery_v": 4.20, "water_temp_f": 52.3}


def test_parse_drops_in_air_reading(export_text):
    assert "2026-09-01" not in {r["date"] for r in solsat.parse(export_text)}


def test_parse_drops_blank_level(export_text):
    assert "2026-09-06" not in {r["date"] for r in solsat.parse(export_text)}


def test_parse_rejects_zero_min(export_text):
    by_date = {r["date"]: r for r in solsat.parse(export_text)}
    assert by_date["2026-09-03"]["min_ft"] is None
    assert by_date["2026-09-03"]["max_ft"] == 0.93


def test_parse_rejects_min_far_from_level(export_text):
    by_date = {r["date"]: r for r in solsat.parse(export_text)}
    assert by_date["2026-09-04"]["min_ft"] is None
    assert by_date["2026-09-04"]["max_ft"] == 0.90


def test_parse_blank_min_max_and_temp(export_text):
    by_date = {r["date"]: r for r in solsat.parse(export_text)}
    assert by_date["2026-09-05"] == {"date": "2026-09-05", "time": "08:00", "level_ft": 0.85, "min_ft": None,
                                     "max_ft": None, "battery_v": 4.19, "water_temp_f": None}


def test_parse_later_line_wins_for_duplicate_date(export_text):
    # Two readings on 07-Sep; parse() keys on the date so the second line in file order replaces the first.
    by_date = {r["date"]: r for r in solsat.parse(export_text)}
    assert by_date["2026-09-07"]["time"] == "14:00"
    assert by_date["2026-09-07"]["level_ft"] == 0.82
    assert by_date["2026-09-07"]["water_temp_f"] == 53.1


def test_parse_skips_unparseable_date_and_short_row(export_text):
    dates = [r["date"] for r in solsat.parse(export_text)]
    assert len(dates) == len(set(dates))
    assert dates.count("2026-09-09") == 1


def test_parse_empty_and_headerless_input():
    assert solsat.parse("") == []
    assert solsat.parse("\n\n   \n") == []
    assert solsat.parse("RID3367:\n") == []
    assert solsat.parse("not,a,portal,export\n1,2,3,4\n") == []


def test_parse_header_only():
    assert solsat.parse(HEADER) == []


def test_parse_sorts_oldest_first_regardless_of_file_order():
    text = HEADER + row("14-Sep-26 8:00 AM", "0.78") + row("12-Sep-26 8:00 AM", "0.79") + row("13-Sep-26 8:00 AM", "0.80")
    assert [r["date"] for r in solsat.parse(text)] == ["2026-09-12", "2026-09-13", "2026-09-14"]


def test_parse_crosses_year_boundary_in_sort():
    text = HEADER + row("02-Jan-27 8:00 AM", "0.70") + row("31-Dec-26 8:00 AM", "0.71")
    assert [r["date"] for r in solsat.parse(text)] == ["2026-12-31", "2027-01-02"]


def test_parse_handles_crlf_and_blank_lines():
    text = HEADER.replace("\n", "\r\n") + "\r\n" + row("14-Sep-26 8:00 AM", "0.78").replace("\n", "\r\n") + "\r\n"
    rows = solsat.parse(text)
    assert len(rows) == 1 and rows[0]["level_ft"] == 0.78


@pytest.mark.parametrize("stamp, date, time", [
    ("14-Sep-26 8:00 AM", "2026-09-14", "08:00"),
    ("14-Sep-26 12:00 AM", "2026-09-14", "00:00"),
    ("14-Sep-26 12:00 PM", "2026-09-14", "12:00"),
    ("14-Sep-26 11:59 PM", "2026-09-14", "23:59"),
    ("4-Sep-26 8:05 AM", "2026-09-04", "08:05"),      # single-digit day
])
def test_parse_time_conversion(stamp, date, time):
    rows = solsat.parse(HEADER + row(stamp, "0.78"))
    assert (rows[0]["date"], rows[0]["time"]) == (date, time)


@pytest.mark.parametrize("stamp", ["2026-09-14 08:00", "14-Sep-2026 8:00 AM", "14-Sep-26 08:00", "14-Sep-26", "Received"])
def test_parse_skips_dates_not_in_portal_format(stamp):
    assert solsat.parse(HEADER + row(stamp, "0.78")) == []


@pytest.mark.parametrize("level, kept", [
    ("0", True), ("0.00", True), ("10", True), ("10.0", True),       # inclusive bounds
    ("-0.01", False), ("10.01", False), ("-1013.42", False),
    ("", False), ("nan", False), ("inf", False), ("n/a", False),
])
def test_parse_level_range_gate(level, kept):
    rows = solsat.parse(HEADER + row("14-Sep-26 8:00 AM", level))
    assert (len(rows) == 1) is kept


@pytest.mark.parametrize("mn, mx, exp_min, exp_max", [
    ("0.74", "0.80", 0.74, 0.80),
    ("0.28", "1.28", 0.28, 1.28),          # exactly 0.5 ft away on either side is allowed
    ("0.27", "1.29", None, None),          # just beyond 0.5 ft
    ("0", "0.80", None, 0.80),             # zero min rejected (must be > 0)
    ("-0.10", "0.80", None, 0.80),         # negative min rejected
    ("", "", None, None),                  # blank
    ("junk", "0.80", None, 0.80),          # unparseable
    ("0.80", "0.74", 0.80, 0.74),          # min > max is not checked; both within 0.5 ft so both kept
])
def test_parse_min_max_sanity(mn, mx, exp_min, exp_max):
    r = solsat.parse(HEADER + row("14-Sep-26 8:00 AM", "0.78", mn, mx))[0]
    assert (r["min_ft"], r["max_ft"]) == (exp_min, exp_max)


def test_parse_min_max_window_follows_level():
    # A min of 4.6 is fine when the level is 5.0 but garbage when the level is 0.78.
    hi = solsat.parse(HEADER + row("14-Sep-26 8:00 AM", "5.0", "4.6", "5.4"))[0]
    lo = solsat.parse(HEADER + row("14-Sep-26 8:00 AM", "0.78", "4.6", "5.4"))[0]
    assert (hi["min_ft"], hi["max_ft"]) == (4.6, 5.4)
    assert (lo["min_ft"], lo["max_ft"]) == (None, None)


def test_parse_uses_header_names_not_positions():
    # Columns reordered relative to the fixture: parse() must still find each by name.
    text = ("RID3367:\n"
            "Received,Max ft,Min ft,Battery Voltage (volts),Water Temp F,Water Level ft\n"
            "14-Sep-26 8:00 AM,0.80,0.74,4.17,51.0,0.78\n")
    assert solsat.parse(text)[0] == {"date": "2026-09-14", "time": "08:00", "level_ft": 0.78, "min_ft": 0.74,
                                     "max_ft": 0.80, "battery_v": 4.17, "water_temp_f": 51.0}


def test_parse_missing_optional_columns_yield_none():
    text = "Received,Water Level ft,Extra,More\n14-Sep-26 8:00 AM,0.78,x,y\n"
    assert solsat.parse(text)[0] == {"date": "2026-09-14", "time": "08:00", "level_ft": 0.78, "min_ft": None,
                                     "max_ft": None, "battery_v": None, "water_temp_f": None}


def test_parse_missing_level_column_yields_nothing():
    text = "Received,Baro ft,Level ft,Min ft\n14-Sep-26 8:00 AM,0.1,0.2,0.3\n"
    assert solsat.parse(text) == []


def test_parse_skips_rows_with_fewer_than_four_fields():
    text = "Received,Water Level ft,Extra\n14-Sep-26 8:00 AM,0.78,x\n"
    assert solsat.parse(text) == []


def test_parse_short_data_row_does_not_index_past_end():
    # Header promises 8 columns; the data row stops after the level. The trailing columns are None, not IndexError.
    text = HEADER + "14-Sep-26 8:00 AM, , ,0.78\n"
    r = solsat.parse(text)[0]
    assert r["level_ft"] == 0.78
    assert (r["min_ft"], r["max_ft"], r["battery_v"], r["water_temp_f"]) == (None, None, None, None)


def test_parse_ignores_lines_before_header():
    text = "RID3367:\nsome,preamble,line,here\n" + HEADER.split("\n", 1)[1] + row("14-Sep-26 8:00 AM", "0.78")
    assert len(solsat.parse(text)) == 1


def test_parse_strips_whitespace_in_header_names():
    text = "Received , Water Level ft , Min ft , Max ft\n14-Sep-26 8:00 AM, 0.78 , 0.74 , 0.80\n"
    r = solsat.parse(text)[0]
    assert (r["level_ft"], r["min_ft"], r["max_ft"]) == (0.78, 0.74, 0.80)


def test_parse_does_not_mutate_input_or_depend_on_trailing_newline(export_text):
    a = solsat.parse(export_text)
    b = solsat.parse(export_text.rstrip("\n"))
    assert a == b


# ------------------------------------------------------------------ write_outputs


def _read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def test_write_outputs_creates_three_files(export_text):
    rows = solsat.parse(export_text)
    solsat.write_outputs(export_text, rows)
    assert sorted(os.listdir(solsat.OUT)) == ["telemetry.csv", "telemetry.js", "telemetry.json"]


def test_write_outputs_csv_is_verbatim(export_text):
    solsat.write_outputs(export_text, solsat.parse(export_text))
    assert _read(os.path.join(solsat.OUT, "telemetry.csv")) == export_text


def test_write_outputs_preserves_crlf():
    text = HEADER.replace("\n", "\r\n") + row("14-Sep-26 8:00 AM", "0.78").replace("\n", "\r\n")
    solsat.write_outputs(text, solsat.parse(text))
    assert _read(os.path.join(solsat.OUT, "telemetry.csv")) == text


def test_write_outputs_meta_and_json(export_text):
    rows = solsat.parse(export_text)
    meta = solsat.write_outputs(export_text, rows)
    assert meta["device"] == "RID3367"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC", meta["fetched"])
    assert meta["n"] == 9
    assert meta["first"] == "2026-09-02"
    assert meta["last"] == "2026-09-14"
    assert meta["columns"] == ["date", "level_ft", "min_ft", "max_ft", "battery_v", "water_temp_f"]
    assert meta["rows"][0] == ["2026-09-02", 0.91, 0.88, 0.95, 4.20, 52.3]
    assert meta["rows"][-1] == ["2026-09-14", 0.78, 0.74, 0.80, 4.17, None]
    assert len(meta["rows"]) == len(rows)
    for m, r in zip(meta["rows"], rows):
        assert m == [r[c] for c in meta["columns"]]
    with open(os.path.join(solsat.OUT, "telemetry.json"), encoding="utf-8") as f:
        assert json.load(f) == meta


def test_write_outputs_json_is_compact(export_text):
    solsat.write_outputs(export_text, solsat.parse(export_text))
    raw = _read(os.path.join(solsat.OUT, "telemetry.json"))
    assert ": " not in raw and ", " not in raw
    assert raw.startswith('{"device":"RID3367"')


def test_write_outputs_js_wraps_same_json(export_text):
    solsat.write_outputs(export_text, solsat.parse(export_text))
    js = _read(os.path.join(solsat.OUT, "telemetry.js"))
    js_json = _read(os.path.join(solsat.OUT, "telemetry.json"))
    assert js == "window.LIVE_TELEMETRY=%s;\n" % js_json
    payload = re.fullmatch(r"window\.LIVE_TELEMETRY=(.*);\n", js, re.S).group(1)
    assert json.loads(payload) == json.loads(js_json)


def test_write_outputs_time_is_not_exported(export_text):
    # "time" is kept on the parsed rows but the published columns are date + values only.
    meta = solsat.write_outputs(export_text, solsat.parse(export_text))
    assert "time" not in meta["columns"]
    assert all(len(r) == 6 for r in meta["rows"])


def test_write_outputs_empty_rows(export_text):
    meta = solsat.write_outputs("RID3367:\n", [])
    assert (meta["n"], meta["first"], meta["last"], meta["rows"]) == (0, None, None, [])
    assert _read(os.path.join(solsat.OUT, "telemetry.csv")) == "RID3367:\n"


def test_write_outputs_creates_missing_nested_dir(tmp_path, monkeypatch, export_text):
    monkeypatch.setattr(solsat, "OUT", str(tmp_path / "a" / "b" / "solsat"))
    solsat.write_outputs(export_text, solsat.parse(export_text))
    assert os.path.exists(os.path.join(solsat.OUT, "telemetry.json"))


def test_write_outputs_overwrites_previous_run(export_text):
    solsat.write_outputs(export_text, solsat.parse(export_text))
    solsat.write_outputs("RID3367:\n", [])
    with open(os.path.join(solsat.OUT, "telemetry.json"), encoding="utf-8") as f:
        assert json.load(f)["n"] == 0


def test_write_outputs_writes_only_under_out(tmp_path, export_text):
    solsat.write_outputs(export_text, solsat.parse(export_text))
    assert sorted(os.listdir(tmp_path)) == ["solsat"]


# -------------------------------------------------------------------------- creds


def test_creds_from_environment(monkeypatch):
    monkeypatch.setenv("SOLSAT_USER", "chris")
    monkeypatch.setenv("SOLSAT_PASS", "s3cret")
    assert solsat.creds() == ("chris", "s3cret")


def test_creds_env_wins_over_file(tmp_path, monkeypatch):
    env = tmp_path / "solsat.env"
    env.write_text("SOLSAT_USER=file-user\nSOLSAT_PASS=file-pass\n")
    monkeypatch.setattr(solsat, "ENV_FILE", str(env))
    monkeypatch.setenv("SOLSAT_USER", "env-user")
    monkeypatch.setenv("SOLSAT_PASS", "env-pass")
    assert solsat.creds() == ("env-user", "env-pass")


def test_creds_from_env_file(tmp_path, monkeypatch):
    env = tmp_path / "solsat.env"
    env.write_text("# portal login\n\nSOLSAT_USER = \"chris\"\nSOLSAT_PASS='p=a=ss'\nOTHER=ignored\n")
    monkeypatch.setattr(solsat, "ENV_FILE", str(env))
    assert solsat.creds() == ("chris", "p=a=ss")


def test_creds_missing_raises(tmp_path, monkeypatch):
    with pytest.raises(SystemExit, match="SOLSAT_USER and SOLSAT_PASS"):
        solsat.creds()
    env = tmp_path / "solsat.env"
    env.write_text("SOLSAT_USER=chris\n")
    monkeypatch.setattr(solsat, "ENV_FILE", str(env))
    with pytest.raises(SystemExit):
        solsat.creds()


def test_conftest_hides_real_env_file():
    assert not os.path.exists(solsat.ENV_FILE)
    assert "SOLSAT_USER" not in os.environ and "SOLSAT_PASS" not in os.environ


# ------------------------------------------------------------------ hidden_fields

LOGIN_PAGE = """<html><body><form method="post" action="./" id="form1">
<input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="/wEPDwUKMTIzNDU2Nzg5ZGQ=" />
<input name="__VIEWSTATEGENERATOR" type="hidden" value="CA0B0334" />
<input type="hidden" name="__EVENTVALIDATION" value="/wEd&#43;AAA&amp;BBB" />
<input type="hidden" name="__EVENTTARGET" />
<input type="text" name="ctl00$cphBody$txtUsername" value="" />
<input type="password" name="ctl00$cphBody$txtPass" />
<input type="submit" name="ctl00$cphBody$btnAuthenticate" value="Login" />
</form></body></html>"""


def test_hidden_fields_extracts_only_hidden_inputs():
    f = solsat.hidden_fields(LOGIN_PAGE)
    assert f == {"__VIEWSTATE": "/wEPDwUKMTIzNDU2Nzg5ZGQ=", "__VIEWSTATEGENERATOR": "CA0B0334",
                 "__EVENTVALIDATION": "/wEd+AAA&BBB", "__EVENTTARGET": ""}


def test_hidden_fields_empty_page():
    assert solsat.hidden_fields("") == {}
    assert solsat.hidden_fields("<html><input type=\"text\" name=\"x\" value=\"1\"></html>") == {}


# ------------------------------------------------------------------------ Portal


class Transport:
    """Records Portal.get/post calls and replays canned responses; never touches the network."""

    def __init__(self, get_pages, post_responses):
        self.get_pages, self.post_responses = list(get_pages), list(post_responses)
        self.gets, self.posts = [], []

    def get(self, path):
        self.gets.append(path)
        return self.get_pages.pop(0)

    def post(self, path, fields):
        self.posts.append((path, dict(fields)))
        return self.post_responses.pop(0)


def stub_portal(monkeypatch, get_pages, post_responses):
    t = Transport(get_pages, post_responses)
    p = solsat.Portal()
    monkeypatch.setattr(p, "get", t.get)
    monkeypatch.setattr(p, "post", t.post)
    return p, t


def test_portal_real_transport_is_blocked():
    with pytest.raises(RuntimeError, match="network"):
        solsat.Portal().get("")
    with pytest.raises(RuntimeError, match="network"):
        solsat.Portal().post("", {})


def test_portal_login_posts_viewstate_and_credentials(monkeypatch):
    p, t = stub_portal(monkeypatch, [LOGIN_PAGE], [("<html><title>Devices</title></html>", solsat.BASE + "Default.aspx")])
    assert p.login("chris", "s3cret") is True
    assert t.gets == [""]
    path, fields = t.posts[0]
    assert path == ""
    assert fields["__VIEWSTATE"] == "/wEPDwUKMTIzNDU2Nzg5ZGQ="
    assert fields["__EVENTVALIDATION"] == "/wEd+AAA&BBB"
    assert fields["ctl00$cphBody$txtUsername"] == "chris"
    assert fields["ctl00$cphBody$txtPass"] == "s3cret"
    assert fields["ctl00$cphBody$btnAuthenticate"] == "Login"


@pytest.mark.parametrize("body", [
    LOGIN_PAGE,                                                   # bounced back to the form (txtPass present)
    "<html><h1>User Login</h1><p>Invalid credentials</p></html>",  # login page without the field
])
def test_portal_login_failure_raises(monkeypatch, body):
    p, _ = stub_portal(monkeypatch, [LOGIN_PAGE], [(body, solsat.BASE)])
    with pytest.raises(SystemExit, match="login failed"):
        p.login("chris", "wrong")


def test_portal_login_user_login_only_checked_near_top(monkeypatch):
    # "User Login" deep in a page (say, a footer link) is not a failure signal.
    body = "<html>" + "x" * 3000 + "User Login</html>"
    p, _ = stub_portal(monkeypatch, [LOGIN_PAGE], [(body, solsat.BASE)])
    assert p.login("chris", "s3cret") is True


DETAIL_PAGE = """<form><input type="hidden" name="__VIEWSTATE" value="detail-vs" />
<input type="hidden" name="__EVENTVALIDATION" value="detail-ev" />
<select name="ctl00$cphBody$ddlReportTime"><option value="24">24</option></select></form>"""


def test_portal_export_csv_posts_save_postback(monkeypatch, export_text):
    p, t = stub_portal(monkeypatch, [DETAIL_PAGE], [(export_text, solsat.BASE)])
    assert p.export_csv("2026214654702", "0", 8760) == export_text
    assert t.gets == ["Detail.aspx?lid=2026214654702&gid=0"]
    path, fields = t.posts[0]
    assert path == "Detail.aspx?lid=2026214654702&gid=0"
    assert fields == {"__VIEWSTATE": "detail-vs", "__EVENTVALIDATION": "detail-ev",
                      "ctl00$cphBody$ddlReportTime": "8760", "__EVENTTARGET": "ctl00$cphBody$lnkSave", "__EVENTARGUMENT": ""}


def test_portal_export_csv_accepts_header_without_title_line(monkeypatch):
    body = "Received,Water Level ft\n14-Sep-26 8:00 AM,0.78\n"
    p, _ = stub_portal(monkeypatch, [DETAIL_PAGE], [(body, solsat.BASE)])
    assert p.export_csv("1", "0", 24) == body


def test_portal_export_csv_rejects_html(monkeypatch):
    p, _ = stub_portal(monkeypatch, [DETAIL_PAGE], [("<html>\n<body>Session expired</body></html>", solsat.BASE)])
    with pytest.raises(SystemExit) as e:
        p.export_csv("1", "0", 24)
    assert str(e.value).startswith("unexpected export response: <html> <body>")


def test_portal_export_csv_error_is_truncated(monkeypatch):
    p, _ = stub_portal(monkeypatch, [DETAIL_PAGE], [("<html>" + "z" * 5000, solsat.BASE)])
    with pytest.raises(SystemExit) as e:
        p.export_csv("1", "0", 24)
    assert len(str(e.value)) < 300


def test_portal_device_constants():
    assert solsat.DEVICE == {"lid": "2026214654702", "gid": "0", "name": "RID3367"}
    assert solsat.HOURS == 8760
    assert solsat.BASE.startswith("https://")


# -------------------------------------------------------------------------- main


class FakePortal:
    """Drop-in for solsat.Portal: records the login and hands back canned export text."""
    instances = []

    def __init__(self):
        self.logins, self.exports = [], []
        FakePortal.instances.append(self)

    def login(self, user, pw):
        self.logins.append((user, pw))
        return True

    def export_csv(self, lid, gid, hours):
        self.exports.append((lid, gid, hours))
        return FakePortal.text


@pytest.fixture
def fake_portal(monkeypatch, export_text):
    FakePortal.instances = []
    FakePortal.text = export_text
    monkeypatch.setattr(solsat, "Portal", FakePortal)
    monkeypatch.setenv("SOLSAT_USER", "chris")
    monkeypatch.setenv("SOLSAT_PASS", "s3cret")
    return FakePortal


@pytest.fixture
def upload_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(solsat, "upload", lambda: calls.append("upload"))
    return calls


def test_main_fetch_writes_outputs_and_uploads(fake_portal, upload_calls, capsys):
    solsat.main([])
    (p,) = fake_portal.instances
    assert p.logins == [("chris", "s3cret")]
    assert p.exports == [("2026214654702", "0", 8760)]
    assert sorted(os.listdir(solsat.OUT)) == ["telemetry.csv", "telemetry.js", "telemetry.json"]
    assert upload_calls == ["upload"]
    out = capsys.readouterr().out
    assert "logged in" in out
    assert "9 daily rows, 2026-09-02 to 2026-09-14, last level 0.78 ft, battery 4.17 V" in out


def test_main_no_upload_skips_upload(fake_portal, upload_calls):
    solsat.main(["--no-upload"])
    assert upload_calls == []
    assert os.path.exists(os.path.join(solsat.OUT, "telemetry.json"))


def test_main_zero_rows_exits_before_writing(fake_portal, upload_calls):
    fake_portal.text = HEADER
    with pytest.raises(SystemExit, match="zero rows"):
        solsat.main([])
    assert not os.path.exists(solsat.OUT)
    assert upload_calls == []


def test_main_missing_creds_exits_before_portal(fake_portal, upload_calls, monkeypatch):
    monkeypatch.delenv("SOLSAT_PASS")
    with pytest.raises(SystemExit, match="SOLSAT_USER and SOLSAT_PASS"):
        solsat.main([])
    assert fake_portal.instances == []


def test_main_parse_mode_reads_file_without_login(fixture_path, upload_calls, capsys, monkeypatch):
    def no_portal():
        raise AssertionError("--parse must not construct a Portal")
    monkeypatch.setattr(solsat, "Portal", no_portal)
    solsat.main(["--parse", fixture_path])
    out = capsys.readouterr().out
    assert "9 rows, 2026-09-02 to 2026-09-14" in out
    assert "'level_ft': 0.78" in out
    assert upload_calls == []
    assert not os.path.exists(solsat.OUT)


def test_main_parse_mode_empty_file(tmp_path, capsys):
    p = tmp_path / "empty.csv"
    p.write_text("")
    solsat.main(["--parse", str(p)])
    assert "0 rows, None to None; last None" in capsys.readouterr().out


def test_upload_skips_when_r2_not_configured(monkeypatch, capsys):
    import r2sync
    monkeypatch.setattr(r2sync, "load_env", lambda: None)
    monkeypatch.setattr(r2sync, "client", lambda env: (_ for _ in ()).throw(AssertionError("no client without env")))
    solsat.upload()
    assert "skipping upload" in capsys.readouterr().out


def test_upload_puts_three_files_to_private_bucket(monkeypatch, capsys, export_text):
    import r2sync
    solsat.write_outputs(export_text, solsat.parse(export_text))
    puts = []
    monkeypatch.setattr(r2sync, "load_env", lambda: {"R2_ACCOUNT_ID": "x"})
    monkeypatch.setattr(r2sync, "client", lambda env: "s3-client")
    monkeypatch.setattr(r2sync, "put", lambda s3, bucket, key, path, cc: puts.append((s3, bucket, key, path, cc)))
    monkeypatch.delenv("SOLSAT_R2_BUCKET", raising=False)
    solsat.upload()
    assert [p[2] for p in puts] == ["telemetry.csv", "telemetry.json", "telemetry.js"]
    assert all(p[0] == "s3-client" and p[1] == "roaring-data" and p[4] == "private, max-age=300" for p in puts)
    assert all(os.path.exists(p[3]) and p[3].startswith(solsat.OUT) for p in puts)
    assert "uploaded 3 files to bucket roaring-data" in capsys.readouterr().out


def test_upload_honours_bucket_override(monkeypatch):
    import r2sync
    puts = []
    monkeypatch.setattr(r2sync, "load_env", lambda: {"R2_ACCOUNT_ID": "x"})
    monkeypatch.setattr(r2sync, "client", lambda env: None)
    monkeypatch.setattr(r2sync, "put", lambda s3, bucket, key, path, cc: puts.append(bucket))
    monkeypatch.setenv("SOLSAT_R2_BUCKET", "roaring-test")
    solsat.upload()
    assert puts == ["roaring-test"] * 3
