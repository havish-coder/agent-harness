"""Lesson 32: fetching a web page, carefully.

`web_fetch(url)` downloads one page and returns its text. It is the agent's way to read
documentation, and for an attacker it is two things at once: a way to bring hostile text into the
conversation (prompt injection, Lesson 31) and a way to send data out (the URL itself can carry it).
So it is built around three guards, all in code the model can't talk its way past:

1. **Where it may connect** (harness/security/netguard.py): only public web servers. The address a
   name resolves to is checked, and the connection goes to *that* address, so private networks,
   this computer and cloud metadata services are out of reach, also after redirects.
2. **How much it takes**: a time limit, a byte limit on what is read (after decompression too), text
   content only, a few redirects.
3. **What happens to the result** (Lessons 29 and 31): permission rules decide per address (asking
   first for each new site), and the page reaches the model fenced as untrusted content, which also
   pauses broad approvals.
"""
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin

import httpx

from harness.security.netguard import Blocked, Resolver, Target, split_url, vet
from harness.tools.base import Tool, tool

MAX_BYTES = 2_000_000          # bytes read from the network, however long the page claims to be
DEFAULT_CHARS = 8_000          # characters returned to the model by default
MAX_CHARS = 30_000
MAX_REDIRECTS = 5
TIMEOUT = 15.0
TEXT_TYPES = ("text/", "application/json", "application/xml", "application/xhtml+xml", "application/rss+xml",
              "application/atom+xml", "application/javascript", "application/x-yaml", "application/yaml")
USER_AGENT = "agent-harness/0.5 (+https://github.com/havish-coder/agent-harness)"
SKIP_TAGS = {"script", "style", "noscript", "template", "svg"}
PARAGRAPH_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "table", "ul", "ol", "blockquote", "section",
                  "article", "main", "header", "footer", "nav", "form"}
LINE_TAGS = {"div", "br", "li", "tr", "hr", "dt", "dd"}


class TextExtractor(HTMLParser):
    """HTML to readable text: no scripts or styles, a blank line between paragraphs, one line per list
    item, links kept as `text (url)`. Line breaks are written only when text follows, so tags with
    nothing inside them leave no gaps."""

    def __init__(self, base: str):
        super().__init__(convert_charrefs=True)
        self.base, self.out, self.skip, self.href, self.pending = base, [], 0, None, 0
        self.title, self.in_title, self.in_head = "", False, False

    def break_before_next_text(self, lines: int) -> None:
        self.pending = max(self.pending, lines)

    def write(self, text: str) -> None:
        if self.out and self.pending:
            self.out.append("\n" * self.pending)
        self.pending = 0
        self.out.append(text)

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self.in_title = True
        elif tag == "head":
            self.in_head = True
        elif tag in SKIP_TAGS:
            self.skip += 1
        if tag in PARAGRAPH_TAGS:
            self.break_before_next_text(2)
        elif tag in LINE_TAGS:
            self.break_before_next_text(1)
        if tag == "a":
            self.href = dict(attrs).get("href")
        if tag == "li" and not self.skip:
            self.write("- ")

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        elif tag == "head":
            self.in_head = False
        elif tag in SKIP_TAGS and self.skip:
            self.skip -= 1
        if tag in PARAGRAPH_TAGS:
            self.break_before_next_text(2)
        elif tag in LINE_TAGS:
            self.break_before_next_text(1)
        if tag == "a" and self.href and not self.skip:
            target = urljoin(self.base, self.href)
            if target.startswith(("http://", "https://")):
                self.out.append(f" ({target})")
        if tag == "a":
            self.href = None

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        elif not self.skip and not self.in_head:
            text = re.sub(r"\s+", " ", data)
            if self.pending or not self.out:
                text = text.lstrip()          # the start of a line
            if text:
                self.write(text)

    def text(self) -> str:
        return "\n".join(line.rstrip() for line in "".join(self.out).splitlines()).strip()


def html_to_text(html: str, base: str) -> tuple[str, str]:
    """(title, text) of an HTML page."""
    parser = TextExtractor(base)
    parser.feed(html)
    parser.close()
    return " ".join(parser.title.split()), parser.text()


def connect_args(target: Target) -> tuple[str, dict]:
    """The URL to request (the address we checked, not the name) and the headers/extensions that keep
    the request addressed to the real host: Host header, TLS server name and certificate check."""
    ip = target.ips[0]
    shown = f"[{ip}]" if ":" in ip else ip
    default = 443 if target.scheme == "https" else 80
    port = "" if target.port == default else f":{target.port}"
    host_header = target.host + port
    return f"{target.scheme}://{shown}{port}{target.path}", {"headers": {"Host": host_header},
                                                              "extensions": {"sni_hostname": target.host}}


class DifferentSite(Exception):
    """The page redirects somewhere else. `url` is where; nothing has been sent to it."""

    def __init__(self, url: str):
        super().__init__(url)
        self.url = url


def same_site(a: str, b: str) -> bool:
    """Same scheme, port and host, ignoring a leading `www.`: the redirects we follow without asking.
    A redirect anywhere else would put a site the user never approved into the conversation."""
    (sa, ha, pa), (sb, hb, pb) = split_url(a), split_url(b)
    return (sa, pa, ha.removeprefix("www.")) == (sb, pb, hb.removeprefix("www."))


def fetch(url: str, allow_local=(), resolver: Resolver = socket.getaddrinfo, transport=None,
          max_bytes: int = MAX_BYTES, timeout: float = TIMEOUT) -> tuple[httpx.Response, bytes, str]:
    """GET `url`, following up to MAX_REDIRECTS redirects within the same site and vetting the address of
    every hop. Returns (the final response, the body bytes read, the final URL). Raises Blocked,
    DifferentSite (a redirect to another site) or httpx errors."""
    current = url
    # trust_env=False: ignore proxy variables, or the check above would be about the proxy, not the page
    with httpx.Client(transport=transport, timeout=timeout, follow_redirects=False, trust_env=False) as client:
        for _ in range(MAX_REDIRECTS + 1):
            target = vet(current, allow_local, resolver)
            request_url, extra = connect_args(target)
            headers = {"User-Agent": USER_AGENT, "Accept": "text/html,text/plain,application/json;q=0.9,*/*;q=0.1",
                       "Accept-Encoding": "gzip", **extra["headers"]}
            with client.stream("GET", request_url, headers=headers, extensions=extra["extensions"]) as response:
                if response.is_redirect and "location" in response.headers:
                    destination = urljoin(current, response.headers["location"])
                    if not same_site(current, destination):
                        raise DifferentSite(destination)
                    current = destination
                    continue
                body = bytearray()
                for chunk in response.iter_bytes():          # after decompression: a zip bomb stops here
                    body += chunk
                    if len(body) >= max_bytes:
                        break
                return response, bytes(body[:max_bytes]), current
    raise Blocked(f"too many redirects (more than {MAX_REDIRECTS})")


def make_web_tools(allow_local=(), resolver: Resolver = socket.getaddrinfo, transport=None) -> list[Tool]:

    @tool(read_only=False, concurrency_safe=True, max_result_chars=MAX_CHARS + 1_000, content_kind="web", clearable=True)
    def web_fetch(url: str, max_chars: int = DEFAULT_CHARS) -> str:
        # The wording is measured (Lesson 32): a description that listed what the tool can't reach made
        # qwen3:4b-instruct answer "I cannot fetch web pages" instead of calling it. The limits are
        # enforced in code and explained in the error message when one is hit.
        """Fetch a web page, or a text, JSON or XML file, and return its text. Use it to read documentation or a
        page the user gave you.

        Args:
            url: The full address, e.g. https://docs.python.org/3/library/pathlib.html
            max_chars: How many characters of the page to return (default 8000).
        """
        max_chars = max(500, min(max_chars, MAX_CHARS))
        try:
            response, body, final = fetch(url, allow_local, resolver, transport)
        except Blocked as e:
            return f"Error: not allowed: {e}. Web pages are fetched from public servers only; don't try another route to the same address."
        except DifferentSite as e:
            return (f"The page redirects to a different site: {e.url}\nNothing was fetched from it. If you want it, call "
                    "web_fetch with that address (the user may be asked first).")
        except httpx.TimeoutException:
            return f"Error: the server didn't answer within {TIMEOUT:.0f} s"
        except httpx.HTTPError as e:
            return f"Error: couldn't fetch the page: {type(e).__name__}: {e}"
        kind = response.headers.get("content-type", "").split(";")[0].strip().lower()
        status = f"HTTP {response.status_code}"
        if kind and not kind.startswith(TEXT_TYPES):
            return f"{status} · {kind} · {final}\nNot shown: this is a {kind} file, not text."
        text = body.decode(response.encoding or "utf-8", errors="replace")
        title = ""
        if kind in ("text/html", "application/xhtml+xml") or (not kind and "<html" in text[:2000].lower()):
            title, text = html_to_text(text, final)
        cut = len(text) > max_chars
        shown = text[:max_chars]
        head = f"{status} · {kind or 'unknown type'} · {final}" + (f" · redirected from {url}" if final != url else "")
        if title:
            head += f"\nTitle: {title}"
        tail = f"\n... [cut: {len(text) - max_chars:,} more characters; ask for more with max_chars]" if cut else ""
        if len(body) >= MAX_BYTES:
            tail += f"\n(the page is larger than {MAX_BYTES:,} bytes; only the start was read)"
        return f"{head}\n\n{shown}{tail}"

    return [web_fetch]

