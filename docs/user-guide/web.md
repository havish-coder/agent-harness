# Reading web pages

The agent has one web tool, `web_fetch`: it downloads **one page** (HTML, plain text, JSON, XML) and
returns its text. It's meant for documentation and for pages you point it to:

```text
you> Read https://docs.python.org/3/library/pathlib.html and tell me how to list files recursively.
  ? web_fetch wants to run
    https://docs.python.org/3/library/pathlib.html
    ! contacts docs.python.org
    allow? [y]es / [n]o / [a]lways allow https://docs.python.org/* (this session):
```

It never runs scripts, submits forms, logs in, or downloads files: a page comes back as text, with
scripts and styles removed and links kept as `text (url)`.

## Permissions
`web_fetch` isn't a read-only tool: a request tells a server something, even if only the address.
So the first fetch from a site asks, and **`a` allows that whole site for the session**
(`web_fetch(https://docs.python.org/*)`). To allow sites for good, add rules to your
[settings](permissions.md#rules):

```json
{ "permissions": { "allow": ["web_fetch(https://docs.python.org/*)", "web_fetch(https://developer.mozilla.org/*)"],
                   "deny":  ["web_fetch(*pastebin*)"] } }
```

- A rule matches the whole address, so `https://docs.python.org/*` does **not** match
  `https://docs.python.org.evil.example/` or `http://docs.python.org/` (a different scheme).
- `plan` mode refuses fetching. `bypass` allows it (until a page has been read: see below);
  `accept-edits` covers file edits only, so fetching still asks.
- The question lists what the address does: the site it contacts, `not encrypted (http)`, and
  *the address carries data after the ?*: anything in a query string is sent to the site.

## Pages are untrusted
Whatever a page says reaches the model **fenced as untrusted content**, and from then on the chat
is [tainted](untrusted-content.md): broad approvals pause. One more rule applies to the web:
once a page has been read, a fetch whose address carries a query string or fragment **asks, even
if you allowed the site**. That is how a hidden instruction in a page would send your data out
(`https://allowed.example/?key=...`), so a person looks at it first.

## Where it can connect
`web_fetch` reaches **public web servers only**. It refuses, with a reason the model can read:

| Address | Why |
|---|---|
| `http://localhost/...`, `http://127.0.0.1/...`, `http://[::1]/...` | this computer: your dev servers, databases, admin panels |
| `http://192.168.x.x`, `10.x.x.x`, `172.16-31.x.x`, `*.local`, `*.internal`, single names like `nas` | your home or office network: routers, printers |
| `http://169.254.169.254/...` | the credentials service of cloud machines |
| `file://`, `ftp://`, and any scheme except http and https | local files, other protocols |
| `http://user:password@host/...` | the part before `@` hides the real host |
| any port except 80 and 443 | internal services listen on other ports |

This holds however the address is written: `2130706433`, `0x7f000001`, `[::ffff:127.0.0.1]`, or a
public-looking name whose DNS record points at `127.0.0.1` are all refused, because the check is on
the address the name **resolves to**, and the connection then goes to that address (so a name can't
answer differently the second time). Redirects are checked the same way.

**Redirects** to the same site (`example.com` to `www.example.com`, or another page) are followed. A
redirect to a *different* site is not: the model is told where the page points, and fetching it
directly asks you about that site.

Other limits: 15 seconds, at most about 2 MB read, text types only (images and archives come back as
"not text"), and proxy environment variables (`HTTPS_PROXY`) are ignored, since a proxy would make the
check about the proxy.

## Your own servers: `web_allow_local`
Sometimes you want the agent to look at a server on your machine, such as the app it is building.
List exactly which ones, in your **user or local** settings (a project can't):

```json
{ "web_allow_local": ["localhost:3000", "127.0.0.1:8000"] }
```

An entry is `host` or `host:port`. Only those hosts skip the address check; everything else stays
blocked. You're still asked about each site as usual.

## Turning it off
`"web_fetch": false` in your settings removes the tool: the agent can't touch the network except
through commands you approve.

## What this isn't
It's not a search engine (the agent needs a URL) and not a browser (no JavaScript: pages that build
their content in the browser come back mostly empty). It isn't a guarantee either: it keeps the
agent off your private network and puts the page in a fence, but a page you allow can still mislead
the model. Treat the answer as you would any web page's content.
