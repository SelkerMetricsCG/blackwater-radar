"""YouTube camera helpers in map.html (ytWatch, ytStatus), run under node; skipped where node is missing."""
import json
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node not installed")


def call(expr):
    with open(os.path.join(ROOT, "map.html"), encoding="utf-8") as f:
        html = f.read()
    block = re.search(r"// BEGIN ytInfo[^\n]*\n(.*?)// END ytInfo", html, re.S).group(1)
    js = block + "\nprocess.stdout.write(JSON.stringify(" + expr + "));"
    env = dict(os.environ, TZ="UTC")
    return json.loads(subprocess.run([NODE, "-e", js], capture_output=True, text=True, check=True, env=env).stdout)


NOW = 1790000000


def test_watch_link_goes_to_the_video_on_youtube():
    assert call("ytWatch('AlJPPPl1yIw')") == "https://www.youtube.com/watch?v=AlJPPPl1yIw"
    assert call("ytWatch('a&b')") == "https://www.youtube.com/watch?v=a%26b"


def test_status_says_when_it_was_last_seen_live_and_when_the_stream_started():
    s = call("ytStatus({since: 1779128422}, %d, %d)" % (NOW - 25 * 60, NOW))
    assert s.startswith("Live-stream thumbnail, live at the last check 25 min ago, streaming since May 18, 2026.")
    assert "sometimes hours late" in s


def test_status_without_times_still_reads():
    assert call("ytStatus({}, null, %d)" % NOW).startswith("Live-stream thumbnail, live now.")
    assert "3 h ago" in call("ytStatus({}, %d, %d)" % (NOW - 3 * 3600, NOW))
