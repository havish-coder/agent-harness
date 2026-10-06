"""Lesson 34: redaction, the audit log, and session limits."""
import json
import time

import pytest

from harness.audit import AuditLog, format_entry, shorten, verify
from harness.limits import Limits
from harness.security.redact import redact, redacted

KEY = "sk-lab-0123456789abcdefghijklmnop"


# --- redaction -----------------------------------------------------------------------------

@pytest.mark.parametrize("text, kind", [
    (f"ANTHROPIC_API_KEY={KEY}", "api key"),
    ("key sk-ant-api03-abcdefghijklmnopqrstuv end", "api key"),
    ("gsk_abcdefghijklmnopqrstuv", "api key"),
    ("AIzaSyA-abcdefghijklmnopqrstuvwxyz12345", "api key"),
    ("ghp_abcdefghijklmnopqrstuvwxyz0123456789", "github token"),
    ("github_pat_" + "a" * 50, "github token"),
    ("AKIAIOSFODNN7EXAMPLE", "aws access key"),
    ("xoxb-1234567890-abcdefghij", "slack token"),
    ("sk_live_abcdefghijklmnop1234", "stripe key"),
    ("eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijklmnop", "jwt"),
    ("Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456", "bearer token"),
    ("postgres://admin:s3cretpass@db.example.com/app", "url password"),
    ("-----BEGIN RSA PRIVATE KEY-----\nMIIEabc\n-----END RSA PRIVATE KEY-----", "private key"),
    ("-----BEGIN OPENSSH PRIVATE KEY-----\ntruncated with no end", "private key"),
    ('db_password: "hunter2hunter2"', "secret value"),
    ("export GITHUB_PASSWORD=correct-horse-battery", "secret value"),
    ("{'client_secret': 'abcdef123456'}", "secret value"),
])
def test_secrets_are_found_by_their_shape(text, kind):
    result = redact(text)
    assert result.found == [kind] and f"[REDACTED: {kind}]" in result.text


def test_only_the_secret_part_goes_so_the_text_stays_readable():
    assert redacted(f"ANTHROPIC_API_KEY={KEY}\nOTHER=fine") == "ANTHROPIC_API_KEY=[REDACTED: api key]\nOTHER=fine"
    assert redacted("Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456") == "Authorization: Bearer [REDACTED: bearer token]"
    assert redacted("postgres://admin:s3cretpass@db.example.com/app") == "postgres://admin:[REDACTED: url password]@db.example.com/app"
    assert redacted('db_password: "hunter2hunter2"') == 'db_password: "[REDACTED: secret value]"'
    assert redacted("-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----\nafter") == "[REDACTED: private key]\nafter"


@pytest.mark.parametrize("text", [
    "TOKEN=1", "MAX_TOKENS=4096", "KEYBOARD=us-international", "password = None", "password: ''", "secret_santa: bob",
    "the word sk-learn is fine", "sk-short", "AKIA is a prefix", "GET https://example.com/a:b@c", "token_count: 5",
    "monkey=bananas123456", "def get_token(): return ''", "api_key = os.environ['KEY']",
])
def test_ordinary_text_is_left_alone(text):
    assert redact(text) == redact(text) and redact(text).found == [] and redact(text).text == text


def test_several_secrets_and_the_counts():
    text = f"A={KEY}\nB=ghp_abcdefghijklmnopqrstuvwxyz0123456789\nC=fine\nDB_PASSWORD=hunter2hunter2"
    result = redact(text)
    assert result.found == ["api key", "github token", "secret value"] and result.count == 3
    assert KEY not in result.text and "hunter2" not in result.text and "C=fine" in result.text


def test_redacting_twice_changes_nothing_more():
    once = redacted(f"X_TOKEN={KEY} and password=hunter2hunter2")
    assert redacted(once) == once


def test_a_python_file_with_a_fake_key_in_a_test_is_redacted_too():
    """The trade-off, stated: shape matching can't tell a test fixture from the real thing."""
    assert KEY not in redacted(f'API_KEY = "{KEY}"  # fixture')


# --- the audit log -------------------------------------------------------------------------

@pytest.fixture
def log(tmp_path):
    return AuditLog(tmp_path / "audit" / "2026-10.jsonl", "abc123")


def lines(log):
    return [json.loads(x) for x in log.path.read_text(encoding="utf-8").splitlines()]


def test_entries_are_json_lines_with_a_chain(log):
    log.write("decision", tool="run_shell", subject="git status", action="allow")
    log.write("result", tool="run_shell", chars=120, error=False)
    first, second = lines(log)
    assert first["kind"] == "decision" and first["session"] == "abc123" and first["tool"] == "run_shell"
    assert first["prev"] == "0" * 16 and second["prev"] != first["prev"] and len(second["prev"]) == 16
    assert verify(log.path) == (True, 2, None)


def test_secrets_never_reach_the_log(log):
    log.write("decision", tool="run_shell", subject=f"curl -H 'Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456' x && echo {KEY}",
              arguments={"content": f"A={KEY}", "list": [KEY, "ok"]})
    text = log.path.read_text(encoding="utf-8")
    assert KEY not in text and "abcdefghijklmnopqrstuvwxyz123456" not in text and "[REDACTED" in text


def test_long_values_are_shortened_and_none_is_left_out(log):
    log.write("result", text="x" * 5000, missing=None, number=3, flag=True)
    entry = lines(log)[0]
    assert len(entry["text"]) == 500 and entry["text"].endswith("…") and "missing" not in entry
    assert entry["number"] == 3 and entry["flag"] is True
    assert shorten({"a": ["b" * 600]})["a"][0].endswith("…")


def test_tampering_is_found(log):
    for i in range(5):
        log.write("result", n=i)
    original = log.path.read_text(encoding="utf-8").splitlines()
    log.path.write_text("\n".join(original[:2] + original[3:]) + "\n", encoding="utf-8")          # one line removed
    ok, count, why = verify(log.path)
    assert not ok and count == 2 and "line 3 doesn't follow line 2" in why
    edited = [original[0], original[1].replace('"n": 1', '"n": 99')] + original[2:]
    log.path.write_text("\n".join(edited) + "\n", encoding="utf-8")                                # one line edited
    assert not verify(log.path)[0]
    log.path.write_text("\n".join([original[0], original[2], original[1]] + original[3:]) + "\n", encoding="utf-8")   # reordered
    assert not verify(log.path)[0]
    log.path.write_text("\n".join(original) + "\nnot json\n", encoding="utf-8")
    assert verify(log.path)[2] == "line 6 isn't valid JSON"


def test_a_new_session_continues_the_chain(log, tmp_path):
    log.write("start")
    again = AuditLog(log.path, "second")
    again.write("start")
    assert verify(log.path) == (True, 2, None) and lines(log)[1]["session"] == "second"


def test_the_log_is_rotated_when_large(log, monkeypatch):
    monkeypatch.setattr("harness.audit.MAX_FILE", 300)
    for i in range(6):
        log.write("result", n=i, padding="x" * 50)
    assert log.path.with_suffix(".jsonl.1").exists() and verify(log.path)[0]


def test_a_log_that_cant_be_written_does_not_stop_the_agent(tmp_path):
    blocked = tmp_path / "file"
    blocked.write_text("x", encoding="utf-8")
    log = AuditLog(blocked / "audit.jsonl", "s")       # its parent is a file, so it can't exist
    log.write("decision")                               # must not raise
    assert log.failed


def test_tail_and_format(log):
    for i in range(30):
        log.write("result", n=i)
    assert [e["n"] for e in log.tail(3)] == [27, 28, 29]
    log.path.write_text(log.path.read_text(encoding="utf-8") + "garbage\n", encoding="utf-8")
    assert log.tail(1)[0]["kind"] == "unreadable line"
    text = format_entry({"t": "2026-10-06T20:11:03", "kind": "decision", "session": "s", "prev": "x", "tool": "run_shell", "n": 3})
    assert text == "20:11:03 decision     tool='run_shell' n=3"


def test_verify_a_missing_file(tmp_path):
    assert verify(tmp_path / "nope.jsonl")[0] is False


# --- limits --------------------------------------------------------------------------------

def test_each_limit_says_what_was_hit():
    limits = Limits(max_tool_calls=3, max_cost=1.0, max_tokens=1000, max_minutes=1)
    assert limits.exceeded() is None
    limits.tool_calls = 3
    assert limits.exceeded() == "3 tool calls (limit 3)"
    limits.tool_calls = 0
    assert limits.exceeded(cost=1.5) == "$1.50 spent (limit $1.00)"
    assert limits.exceeded(cost=None) is None             # an unpriced model has no cost limit
    assert limits.exceeded(tokens=1500) == "1,500 tokens used (limit 1,000)"
    limits.started -= 120
    assert "2 minutes (limit 1)" in limits.exceeded()


def test_no_limits_means_no_stops():
    limits = Limits(None, None, None, None)
    limits.tool_calls = 10**6
    limits.started -= 10**6
    assert limits.exceeded(tokens=10**9, cost=10**6) is None


def test_reset_starts_counting_again():
    limits = Limits(max_tool_calls=1)
    limits.tool_calls = 1
    assert limits.exceeded()
    limits.reset()
    assert limits.exceeded() is None and time.monotonic() - limits.started < 1
