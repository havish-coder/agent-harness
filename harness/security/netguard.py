"""Lesson 32: deciding whether a web address is safe to connect to.

The risk is **server-side request forgery (SSRF)**: the model, steered by text it read, asks the
agent to fetch an address that is reachable from *your machine* but not from the internet:
`http://169.254.169.254/` (a cloud provider's credentials service), `http://localhost:8080/admin`,
`http://192.168.1.1/` (your router). The agent is the deputy that can reach them.

`vet(url)` raises `Blocked` unless every address the name resolves to is a public one. It is
checked on the *resolved* addresses, not on the spelling of the URL, because the same address has
many spellings (`2130706433`, `0x7f.1`, `[::ffff:127.0.0.1]`, a name that points to 127.0.0.1).
The caller then connects to the address that was checked, so the name can't resolve differently a
moment later (DNS rebinding).
"""
import ipaddress
import re
import socket
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from urllib.parse import urlsplit

ALLOWED_SCHEMES = ("http", "https")
ALLOWED_PORTS = (80, 443)
BLOCKED_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home", ".corp", ".intranet")
# Address blocks that embed another address or are only ever used inside a network, even where
# Python's `is_global` can't say so: tunnels (Teredo, 6to4, NAT64) could carry a private IPv4.
EXTRA_BLOCKED = [ipaddress.ip_network(n) for n in ("64:ff9b::/96", "64:ff9b:1::/48", "2001::/32", "2002::/16",
                                                   "100.64.0.0/10", "192.0.0.0/24", "198.18.0.0/15", "fc00::/7")]
Resolver = Callable[..., list]
DISGUISED_IP = re.compile(r"(?:0x[0-9a-f]+|\d+)(?:\.(?:0x[0-9a-f]+|\d+))*", re.IGNORECASE)   # 2130706433, 0x7f.1, 0177.0.0.1


class Blocked(ValueError):
    """The address may not be fetched. The message says why, in words for the user and the model."""


@dataclass
class Target:
    url: str
    scheme: str
    host: str                    # without brackets, lower case, IDNA-encoded
    port: int
    ips: list[str] = field(default_factory=list)    # every address the host resolves to (all were checked)

    @property
    def path(self) -> str:
        parts = urlsplit(self.url)
        return (parts.path or "/") + (f"?{parts.query}" if parts.query else "")


def check_ip(ip: str) -> str | None:
    """Why this address may not be fetched, or None when it is a public one."""
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return f"'{ip}' is not an IP address"
    if address.version == 6 and address.ipv4_mapped:
        return check_ip(str(address.ipv4_mapped))                   # ::ffff:127.0.0.1 is 127.0.0.1
    if address.is_loopback:
        return f"{ip} is this computer (loopback)"
    if address.is_link_local:
        return f"{ip} is a link-local address (cloud metadata services live here)"
    if address.is_private:
        return f"{ip} is a private network address"
    if address.is_multicast or address.is_unspecified or address.is_reserved:
        return f"{ip} is not a public address"
    if any(address in net for net in EXTRA_BLOCKED if net.version == address.version):
        return f"{ip} is in a range used inside networks or for tunnels"
    return None if address.is_global else f"{ip} is not a public address"


def split_url(url: str) -> tuple[str, str, int]:
    """(scheme, host, port) of a URL we are willing to look at, or Blocked."""
    if any(ch in url for ch in "\\\r\n\t ") or any(ord(ch) < 32 or ord(ch) == 127 for ch in url):
        raise Blocked("the URL contains spaces, backslashes or control characters")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise Blocked("the URL can't be read") from None
    scheme = parts.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise Blocked(f"only http and https addresses can be fetched, not '{scheme or url.split(':')[0]}'")
    if "@" in parts.netloc:
        raise Blocked("addresses with a user name or password (user@host) are refused: they hide the real host")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise Blocked("the URL has no host")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        raise Blocked("the host name can't be encoded") from None
    return scheme, host, port or (443 if scheme == "https" else 80)


def is_literal_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def allowed_local(host: str, port: int, allow_local: Iterable[str]) -> bool:
    """Is `host` or `host:port` one the user listed in the web_allow_local setting?"""
    return any(entry.lower() in (host, f"{host}:{port}") for entry in allow_local)


def vet(url: str, allow_local: Iterable[str] = (), resolver: Resolver = socket.getaddrinfo) -> Target:
    """Check one address (also used for every redirect). Returns where to connect, or raises Blocked."""
    scheme, host, port = split_url(url)
    local = allowed_local(host, port, allow_local)
    if not local:
        # The most telling reason first: what the address is, then the name, then the port.
        why = check_ip(host) if is_literal_ip(host) else None
        if why:
            raise Blocked(f"'{host}' is not a public web address: {why}")
        if DISGUISED_IP.fullmatch(host) and not is_literal_ip(host):
            raise Blocked(f"'{host}' is an unusual way to write an IP address (decimal, hex or octal parts): "
                          "that is how internal addresses are disguised")
        if host == "localhost" or host.endswith(BLOCKED_SUFFIXES) or "." not in host and not is_literal_ip(host):
            raise Blocked(f"'{host}' is a local name, not a public web address")
        if port not in ALLOWED_PORTS:
            raise Blocked(f"port {port} isn't allowed: web pages are fetched from port 80 or 443 only")
    try:
        found = resolver(host, port, type=socket.SOCK_STREAM)
    except OSError as e:
        raise Blocked(f"can't find '{host}': {e}") from None
    ips = list(dict.fromkeys(item[4][0].split("%")[0] for item in found))
    if not ips:
        raise Blocked(f"'{host}' doesn't resolve to any address")
    if not local:
        for ip in ips:                               # all of them: one private answer is enough to refuse
            why = check_ip(ip)
            if why:
                raise Blocked(f"'{host}' resolves to {why}. Only public web servers can be fetched")
    return Target(url, scheme, host, port, ips)
