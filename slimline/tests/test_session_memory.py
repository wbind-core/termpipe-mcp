"""Tests for slimline/tools/session_memory.py (context-core slice)."""
import os
import tempfile

import pytest

os.environ["SLIMLINE_SESSIONS_DB"] = os.path.join(
    tempfile.mkdtemp(), "test-sessions.db")

from slimline.tools import session_memory as sm


def test_score_significance():
    assert sm.score_significance("decision") == 0.9
    assert sm.score_significance("note") == 0.6
    assert sm.score_significance("error") == 0.75
    assert sm.score_significance("task") == 0.7
    assert sm.score_significance("note", pinned=True) == 1.0
    assert sm.score_significance("bogus-kind") == 0.5


def test_touch_and_briefing_roundtrip(tmp_path):
    cwd = str(tmp_path / "proj")
    sm.touch_session(cwd)
    sm.touch_session(cwd)
    sig = sm.add_note(cwd, "decision", "Chose X over Y", pinned=True)
    assert sig == 1.0
    b = sm.briefing(cwd)
    assert "visit #2" in b
    assert "Chose X over Y" in b
    assert "[decision]" in b


def test_briefing_first_visit_empty(tmp_path):
    cwd = str(tmp_path / "fresh")
    sm.touch_session(cwd)
    b = sm.briefing(cwd)
    assert "first visit" in b
    assert "session_note" in b


def test_recall_keyword_filter(tmp_path):
    cwd = str(tmp_path / "proj2")
    sm.add_note(cwd, "note", "the database schema changed")
    sm.add_note(cwd, "note", "unrelated observation")
    r = sm.recall(cwd, query="schema")
    assert "database schema" in r
    assert "unrelated" not in r


def test_log_event_no_crash(tmp_path):
    sm.log_event(str(tmp_path / "proj3"), "error", "boom", "detail")
