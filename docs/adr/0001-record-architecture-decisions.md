# 0001. Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-10-06

## Context
The project makes many design choices (formats, dependencies, security trade-offs). Code shows
*what* was built but not *why*, or which alternatives were rejected. Six months later, nobody
remembers, and the same debates happen again.

## Options
1. **No written record**: fastest now; the reasoning is lost.
2. **A design wiki page**: one big page that drifts out of date and has no history.
3. **Architecture decision records** (Michael Nygard's format): one short file per decision,
   versioned with the code.

## Decision
Use ADRs in `docs/adr/`, numbered, using [the template](template.md). Accepted ADRs are not
edited; a new ADR supersedes an old one.

## Consequences
- Every pull request that makes a real choice adds an ADR (see CONTRIBUTING.md).
- Reviewers can check a change against the decisions it relies on.
- Small cost: a few minutes of writing per decision.
