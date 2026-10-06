# 0012. Test agent behaviour with recorded model runs

- **Status:** Accepted
- **Date:** 2026-10-06

## Context
Unit tests with hand-written replies check the loop's rules, but not what happens when a real
model drives real tools. Running the real model in tests is slow (tens of seconds per task),
needs a GPU, and gives different answers each time, so such tests are flaky and rarely run.

## Options
1. **Unit tests only**: fast and stable; nothing checks the end-to-end behaviour.
2. **Live tests in the suite**: realistic; slow, flaky, impossible in CI without a GPU.
3. **Record and replay**: record a real run once (requests and replies), replay the replies
   in tests while the real tools run, and fail if the agent's requests differ from the recording.

## Decision
Option 3 for regression tests, plus a small set of live tests behind a `live` marker. Cassettes
are JSON Lines, one model call per line, with machine-specific text (workspace path, home
folder, Python install, timings, path separators) replaced by placeholders. Replays are strict
by default.

## Consequences
- The suite replays a real bug-fix run (5 model calls) in about 2 seconds, without a model.
- Intended changes to prompts or tool output break the replay; the cassette must then be
  re-recorded, and its diff reviewed. That friction is the point: behaviour changes are visible.
- A cassette pins one model's behaviour at one moment. It says nothing about other models;
  that is the job of evals (v1.0).
- Cassettes are committed, so they must never contain personal paths or secrets; a test checks
  for the home folder path.
