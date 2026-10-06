# 0029. Fetch web pages through an address guard that connects to the address it checked

- **Status:** Accepted
- **Date:** 2026-10-06

## Context
A coding agent needs documentation, and models don't know every API. A `web_fetch` tool is the
obvious answer, and it is the first tool that reaches **the network on the agent's own authority**.
That brings three of the threats in the [threat model](../security.md):

- **T10, server-side request forgery.** The model, steered by text it read, asks for
  `http://169.254.169.254/` (cloud credentials), `http://localhost:8080/admin` or the router's
  page. The agent can reach them; the internet can't.
- **T8, data out.** The address itself can carry data (`https://x.example/?k=<secret>`).
- **T9, prompt injection.** A page is the easiest way to put attacker text into the conversation.

## Options for the address check
1. **Check the hostname's spelling** (block `localhost`, `127.*`, `10.*` ...). Easy to evade: `2130706433`,
   `0x7f.1`, `[::ffff:127.0.0.1]`, a public name with a DNS record for 127.0.0.1.
2. **Resolve, check the addresses, then let the HTTP library resolve again and connect.** Defeated by
   *DNS rebinding*: the name answers a public address the first time and `127.0.0.1` the second.
3. **Resolve once, check every address, and connect to the address that was checked** (sending the
   host name in the `Host` header and as the TLS server name, so certificates are still verified).
4. **Fetch through a proxy or a separate network namespace with no route to private ranges.** The
   strongest, but not available on a user's laptop without setup; worth documenting for deployments.

For redirects: follow any (checking each), follow only same-site ones, or follow none.

## Decision
Option 3 (`harness/security/netguard.py`, `harness/tools/web.py`):

- `vet(url)` accepts only http and https, no user-info, no spaces or control characters, ports 80 and
  443, and a host whose **every** resolved address is public (not loopback, link-local, private,
  carrier-grade NAT, multicast, reserved, or in a tunnel range that can embed a private IPv4;
  IPv4-mapped IPv6 is unwrapped). Names like `localhost`, `*.local` and single labels are refused
  before resolving.
- The request goes to the checked IP, with `Host` and TLS server name (`sni_hostname`) set to the name.
- **Redirects:** followed only to the same site (same scheme, port and host, ignoring `www.`), and each
  hop is vetted again. A redirect elsewhere is not followed: the model is told where the page points,
  and a direct fetch of that address goes through the permission rules like any other. This keeps an
  allowed site (or an open redirect on it) from importing content from a site the user never
  approved. (Claude Code's tool makes the same choice.)
- Proxy environment variables are ignored; 15 s timeout; at most about 2 MB read, counted *after*
  decompression; text content types only.
- **Permissions** (ADR 0026): the tool has a `url` subject and isn't read-only, so the first fetch from
  a site asks and "always" adds a rule for that site (`scheme://host/*`). Plan mode refuses it.
  Approval questions list the host, plain http, and any query string. After untrusted content has
  been read, an address with a query or fragment asks even if a rule allows the site.
- **Pages are untrusted** (ADR 0028): fenced, and they taint the chat in every folder.
- `web_allow_local` (user and local settings only) names exact `host[:port]` entries that skip the
  address check, for the user's own dev servers. `web_fetch: false` removes the tool.

## Consequences
- The three classic bypasses (alternative spellings, rebinding, redirects into the private network)
  are closed in code, with tests that use a fake resolver and a mock transport that records where each
  request was really sent.
- The agent can no longer look at the app it is building without a setting. That is deliberate: the
  safe default has a documented, narrow, user-only exception.
- Resolving first costs a DNS lookup per hop, and a site with several addresses uses the first;
  connect failures aren't retried against the others (a possible refinement).
- A page can still say anything; the guard doesn't read it. Its limits are exactly those of fencing and
  taint.
- Not covered: a malicious *public* server that the user allows; and processes started by approved shell
  commands (`curl`), which only the permission rules and, later, a sandbox can limit.
