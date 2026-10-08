# 0055. Web UI security: an attack lab, then an origin check, JSON-only requests, security headers and a private opener

- **Status:** Accepted
- **Date:** 2026-10-08

## Context
The web UI (ADRs 0051 to 0054) can do everything the terminal can, and its page can approve tool calls. From the start it listened on
127.0.0.1 only, checked the `Host` header against DNS rebinding, and needed a key per start, swapped on the first visit for an
`HttpOnly`, `SameSite=Strict` cookie. The page escaped every piece of model text before adding its own tags and never loaded pictures.

That was designed, not measured. `scripts/web_attack_lab.py` attacks the server and the page as three attackers would: a site open in
the same browser, a model that read something hostile, and another program or user on the computer. On the code before this decision
it blocked **11 of 18**. Open:

1. a request carrying the cookie from another site (a browser without `SameSite`, or one where it is turned off);
2. an HTML form posting `text/plain` that happens to be JSON (forms can't send `application/json`, but the server parsed any body);
3. framing: no `X-Frame-Options`, no `frame-ancestors`, so another site could put the page in an invisible frame over a button;
4. no `Content-Security-Policy`: a script that got into the page by any bug would run, and could load more from anywhere;
5. no `X-Content-Type-Options: nosniff`;
6. no `Referrer-Policy`;
7. the key on the browser's command line: `webbrowser.open(url)` starts the browser with the address, key included, as an argument,
   which other users can read in a process list (on Linux, `/proc/<pid>/cmdline` is readable by everyone).

## Decision
`harness/web/server.py`:

- **POSTs must say they come from the page**: when the browser sends `Origin` (it always does for `fetch` POSTs), it must be
  `http://127.0.0.1:PORT` or `http://localhost:PORT`, else 403. A request without `Origin` (a script of yours, `curl`) still needs the key.
- **POSTs must be JSON**: `Content-Type: application/json`, else 415. An HTML form can't send it, and a cross-site `fetch` with it
  needs a CORS preflight the server never answers.
- **A body over 1 MB** is refused with 413 before it is read. Any other body is **read before a request is refused**: a refusal that left
  the body unread closed a socket with data in it, which Windows answers with a reset, so the client often saw a broken connection
  instead of the 401 or 403 (found by the test for the origin check; it had also made an earlier test flaky). A test sends 30 refused
  requests with 200 KB bodies: with the old order it failed every run, with the new one it passes.
- **Security headers on every answer** (`Handler.end_headers`): `Content-Security-Policy: default-src 'none'; script-src 'self';
  style-src 'self'; img-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'`,
  `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cross-Origin-Opener-Policy: same-origin`,
  `Cross-Origin-Resource-Policy: same-origin`. The page needed no change: it has no inline script or style, no handler attributes, and
  loads nothing from elsewhere (a test checks the files).
- **A private opener** (`open_page`): the browser is given a file in the temporary folder (created readable by you only) that redirects
  to the address; the file is deleted when the server stops. The address with the key is printed in your terminal as before.

## Consequences
- The lab now blocks **18 of 18**. Each check is also a test (`tests/test_web_server.py`, `tests/test_web_page.py`).
- Defense in depth, not a new wall: `SameSite=Strict` already kept the cookie off other sites' requests in current browsers; the origin
  and content-type checks hold where it doesn't, and the policy limits what any future bug in the page could do.
- Not covered, stated in the security docs: someone with administrator rights or a program running as you (they can read the cookie,
  the private file or the terminal, and could run commands anyway); a browser extension allowed to read every page.
- Not done (YAGNI): HTTPS (the traffic never leaves the machine), rate limits (a local attacker with the key doesn't need speed), a key that
  survives restarts.
