"""
Shared setup for the radar tests.

Every test runs with urllib's HTTP blocked, so nothing reaches the network, and
with the repo root on sys.path so tests can import the job modules directly.
"""
import os
import sys
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _no_network(*args, **kwargs):
    raise RuntimeError("network access attempted during tests")


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    """Block urllib HTTP for every test."""
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", _no_network)
    monkeypatch.setattr(urllib.request, "urlopen", _no_network)
    yield
