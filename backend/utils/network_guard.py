"""Process-wide offline guard: refuses outbound connections to anything but this machine.

Installed at startup (STRICT_OFFLINE, on by default) so no library can upload document
content or phone home. Loopback (Ollama, the local UI) keeps working.
"""
from __future__ import annotations

import ipaddress
import socket
import threading
from contextlib import contextmanager

_installed = False
_ctx = threading.local()


@contextmanager
def allow_hosts(hosts: list[str]):
    """Temporarily permit connections from THIS thread to the given hostnames only
    (used exclusively by ExternalAssetManager for approved image providers)."""
    ips: set[str] = set()
    for h in hosts:
        try:
            for ai in socket.getaddrinfo(h, 443, proto=socket.IPPROTO_TCP):
                ips.add(ai[4][0].split("%")[0])
        except OSError:
            continue
    prev = getattr(_ctx, "ips", frozenset())
    _ctx.ips = frozenset(prev | ips)
    try:
        yield
    finally:
        _ctx.ips = prev


def _permitted(address) -> bool:
    if _is_local(address):
        return True
    host = address[0] if isinstance(address, tuple) and address else ""
    return str(host).split("%")[0] in getattr(_ctx, "ips", frozenset())
_orig_connect = socket.socket.connect
_orig_connect_ex = socket.socket.connect_ex
_orig_create_connection = socket.create_connection


class NetworkBlocked(ConnectionRefusedError):
    pass


def _is_local(address) -> bool:
    if isinstance(address, tuple) and address:
        host = address[0]
    elif isinstance(address, (str, bytes)):  # AF_UNIX paths
        return True
    else:
        return True
    host = host.decode() if isinstance(host, bytes) else str(host)
    if host in ("localhost", "") or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        try:
            return all(ipaddress.ip_address(ai[4][0].split("%")[0]).is_loopback
                       for ai in socket.getaddrinfo(host, None))
        except OSError:
            return False


def _guarded_connect(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6) and not _permitted(address):
        raise NetworkBlocked(f"Outbound network access is disabled (offline mode): {address[0]}")
    return _orig_connect(self, address)


def _guarded_connect_ex(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6) and not _permitted(address):
        raise NetworkBlocked(f"Outbound network access is disabled (offline mode): {address[0]}")
    return _orig_connect_ex(self, address)


def install() -> None:
    global _installed
    if _installed:
        return
    socket.socket.connect = _guarded_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = _guarded_connect_ex  # type: ignore[method-assign]
    _installed = True


def uninstall() -> None:
    global _installed
    socket.socket.connect = _orig_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = _orig_connect_ex  # type: ignore[method-assign]
    _installed = False


def is_installed() -> bool:
    return _installed
