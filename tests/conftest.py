"""
Shared setup for the solsat tests.

Every test runs with the network blocked, solsat.env pointed at a path that
does not exist, SOLSAT_USER/SOLSAT_PASS removed from the environment, and the
output folder redirected into a per-test tmp_path. Tests that need credentials
or a portal set them up explicitly on top of this baseline.
"""
import os
import sys
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import solsat  # noqa: E402  (needs ROOT on sys.path first)

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def _no_network(*args, **kwargs):
    raise RuntimeError("network access attempted during tests")


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    """Block sockets-level HTTP, hide solsat.env and the real creds, sandbox OUT."""
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", _no_network)
    monkeypatch.setattr(urllib.request, "urlopen", _no_network)
    monkeypatch.setattr(solsat, "ENV_FILE", str(tmp_path / "does-not-exist.env"))
    monkeypatch.setattr(solsat, "OUT", str(tmp_path / "solsat"))
    monkeypatch.delenv("SOLSAT_USER", raising=False)
    monkeypatch.delenv("SOLSAT_PASS", raising=False)
    yield


@pytest.fixture
def fixture_path():
    return os.path.join(FIXTURES, "solsat_export.csv")


@pytest.fixture
def export_text(fixture_path):
    # main() reads the export with latin-1; do the same here.
    with open(fixture_path, encoding="latin-1") as f:
        return f.read()
