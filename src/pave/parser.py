import base64
import json
import logging
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse

from .models import ProxyConfig

logger = logging.getLogger(__name__)


def parse_config(raw: str, source: str = "") -> Optional[ProxyConfig]:
    raw = raw.strip()
    try:
        if raw.startswith("vless://"):
            return _parse_vless(raw, source)
        elif raw.startswith("vmess://"):
            return _parse_vmess(raw, source)
        elif raw.startswith("ss://"):
            return _parse_shadowsocks(raw, source)
        elif raw.startswith("trojan://"):
            return _parse_trojan(raw, source)
        elif raw.startswith("ssr://"):
            return _parse_ssr(raw, source)
        elif raw.startswith(("hysteria2://", "hy2://")):
            return _parse_hysteria2(raw, source)
        elif raw.startswith(("socks://", "socks4://", "socks5://")):
            return _parse_socks(raw, source)
        elif raw.startswith("tuic://"):
            return _parse_tuic(raw, source)
    except Exception as e:
        logger.debug(f"Parse error: {e!r} | {raw[:80]}")
    return None


def _parse_vless(raw: str, source: str) -> Optional[ProxyConfig]:
    parsed = urlparse(raw)
    if not parsed.hostname or not parsed.port:
        return None
    qs = _qs(parsed.query)
    name = unquote(parsed.fragment) if parsed.fragment else f"{parsed.hostname}:{parsed.port}"
    return ProxyConfig(
        raw=raw, protocol="vless",
        server=parsed.hostname, port=parsed.port, name=name, source=source,
        params={
            "uuid":          parsed.username or "",
            "security":      qs.get("security", "none"),
            "encryption":    qs.get("encryption", "none"),
            "type":          qs.get("type", "tcp"),
            "sni":           qs.get("sni", ""),
            "fp":            qs.get("fp", ""),
            "path":          qs.get("path", "/"),
            "host":          qs.get("host", ""),
            "flow":          qs.get("flow", ""),
            "pbk":           qs.get("pbk", ""),
            "sid":           qs.get("sid", ""),
            "spx":           unquote(qs.get("spx", "")),
            "serviceName":   qs.get("serviceName", ""),
            "mode":          qs.get("mode", "gun"),
            "headerType":    qs.get("headerType", "none"),
            "allowInsecure": qs.get("allowInsecure", "0"),
        },
    )


def _parse_vmess(raw: str, source: str) -> Optional[ProxyConfig]:
    b64 = raw[len("vmess://"):].split("#")[0]
    try:
        data = json.loads(base64.b64decode(b64 + "==").decode("utf-8", errors="ignore"))
    except Exception:
        return None

    server = data.get("add", "")
    try:
        port = int(data.get("port", 0))
    except (ValueError, TypeError):
        return None
    if not server or not port:
        return None

    return ProxyConfig(
        raw=raw, protocol="vmess",
        server=server, port=port,
        name=data.get("ps", f"{server}:{port}"),
        source=source,
        params={
            "uuid":       data.get("id", ""),
            "alterId":    int(data.get("aid", 0) or 0),
            "security":   data.get("scy", "auto"),
            "type":       data.get("net", "tcp"),
            "tls":        data.get("tls", ""),
            "sni":        data.get("sni", "") or data.get("host", ""),
            "path":       data.get("path", "/"),
            "host":       data.get("host", ""),
            "headerType": data.get("type", "none"),
            "fp":         data.get("fp", ""),
        },
    )


def _parse_shadowsocks(raw: str, source: str) -> Optional[ProxyConfig]:
    body = raw[len("ss://"):]
    name = ""
    if "#" in body:
        body, frag = body.split("#", 1)
        name = unquote(frag)

    plugin = ""
    if "?" in body:
        body, query = body.split("?", 1)
        plugin = parse_qs(query).get("plugin", [""])[0]

    if "@" in body:
        userinfo, hostport = body.rsplit("@", 1)
        method, password = _decode_ss_userinfo(userinfo)
        host, port = _split_host_port(hostport)
    else:
        try:
            decoded = base64.b64decode(body + "==").decode("utf-8", errors="ignore")
        except Exception:
            return None
        if "@" not in decoded:
            return None
        userinfo, hostport = decoded.rsplit("@", 1)
        method, password = _decode_ss_userinfo(userinfo)
        host, port = _split_host_port(hostport)

    if not host or not port:
        return None
    if not name:
        name = f"{host}:{port}"

    return ProxyConfig(
        raw=raw, protocol="ss",
        server=host, port=port, name=name, source=source,
        params={"method": method, "password": password, "plugin": plugin},
    )


def _decode_ss_userinfo(userinfo: str):
    try:
        decoded = base64.b64decode(userinfo + "==").decode("utf-8", errors="ignore")
        if ":" in decoded:
            method, password = decoded.split(":", 1)
            return method.strip(), password.strip()
    except Exception:
        pass
    if ":" in userinfo:
        method, password = userinfo.split(":", 1)
        return method.strip(), password.strip()
    return "aes-256-gcm", userinfo


def _split_host_port(hostport: str):
    hostport = hostport.strip().rstrip("/")
    if ":" not in hostport:
        return hostport, None
    host, port_str = hostport.rsplit(":", 1)
    try:
        return host.strip("[]"), int(port_str)
    except ValueError:
        return host, None


def _parse_trojan(raw: str, source: str) -> Optional[ProxyConfig]:
    parsed = urlparse(raw)
    if not parsed.hostname or not parsed.port:
        return None
    qs = _qs(parsed.query)
    name = unquote(parsed.fragment) if parsed.fragment else f"{parsed.hostname}:{parsed.port}"
    return ProxyConfig(
        raw=raw, protocol="trojan",
        server=parsed.hostname, port=parsed.port, name=name, source=source,
        params={
            "password":      unquote(parsed.username or ""),
            "security":      qs.get("security", "tls"),
            "sni":           qs.get("sni", ""),
            "type":          qs.get("type", "tcp"),
            "path":          qs.get("path", "/"),
            "host":          qs.get("host", ""),
            "fp":            qs.get("fp", ""),
            "headerType":    qs.get("headerType", "none"),
            "allowInsecure": qs.get("allowInsecure", "0"),
        },
    )


def _parse_ssr(raw: str, source: str) -> Optional[ProxyConfig]:
    body = raw[len("ssr://"):]
    try:
        decoded = base64.urlsafe_b64decode(body + "==").decode("utf-8", errors="ignore")
    except Exception:
        return None

    main, _, query_part = decoded.partition("?")
    parts = main.rstrip("/").split(":")
    if len(parts) < 6:
        return None

    host = parts[0]
    try:
        port = int(parts[1])
    except ValueError:
        return None
    ssr_protocol = parts[2]
    method = parts[3]
    obfs = parts[4]
    pass_b64 = parts[5].split("/")[0]

    try:
        password = base64.urlsafe_b64decode(pass_b64 + "==").decode("utf-8", errors="ignore")
    except Exception:
        password = pass_b64

    qs = parse_qs(query_part) if query_part else {}
    remarks_b64 = (qs.get("remarks") or [""])[0]
    try:
        name = base64.urlsafe_b64decode(remarks_b64 + "==").decode("utf-8", errors="ignore") if remarks_b64 else f"{host}:{port}"
    except Exception:
        name = f"{host}:{port}"

    def _b64qs(key: str) -> str:
        val = (qs.get(key) or [""])[0]
        if not val:
            return ""
        try:
            return base64.urlsafe_b64decode(val + "==").decode("utf-8", errors="ignore")
        except Exception:
            return val

    return ProxyConfig(
        raw=raw, protocol="ssr",
        server=host, port=port, name=name, source=source,
        params={
            "method":         method,
            "password":       password,
            "protocol":       ssr_protocol,
            "obfs":           obfs,
            "obfs_param":     _b64qs("obfsparam"),
            "protocol_param": _b64qs("protoparam"),
        },
    )


def _parse_hysteria2(raw: str, source: str) -> Optional[ProxyConfig]:
    normalised = "hysteria2://" + raw.split("://", 1)[1]
    parsed = urlparse(normalised)
    if not parsed.hostname or not parsed.port:
        return None
    qs = _qs(parsed.query)
    name = unquote(parsed.fragment) if parsed.fragment else f"{parsed.hostname}:{parsed.port}"
    password = unquote(parsed.username or "")
    return ProxyConfig(
        raw=raw, protocol="hysteria2",
        server=parsed.hostname, port=parsed.port, name=name, source=source,
        params={
            "password":      password,
            "sni":           qs.get("sni", ""),
            "insecure":      qs.get("insecure", "0"),
            "obfs":          qs.get("obfs", ""),
            "obfs_password": qs.get("obfs-password", ""),
            "up_mbps":       qs.get("up", ""),
            "down_mbps":     qs.get("down", ""),
        },
    )


def _parse_socks(raw: str, source: str) -> Optional[ProxyConfig]:
    parsed = urlparse(raw)
    if not parsed.hostname or not parsed.port:
        return None
    name = unquote(parsed.fragment) if parsed.fragment else f"{parsed.hostname}:{parsed.port}"
    username, password = "", ""
    if parsed.username:
        userinfo = unquote(parsed.username)
        try:
            decoded = base64.b64decode(userinfo + "==").decode("utf-8", errors="ignore")
            if ":" in decoded:
                username, password = decoded.split(":", 1)
            else:
                username = decoded
        except Exception:
            username = userinfo
        if parsed.password:
            password = unquote(parsed.password)
    version = "5" if "5" in parsed.scheme else ("4" if "4" in parsed.scheme else "5")
    return ProxyConfig(
        raw=raw, protocol="socks",
        server=parsed.hostname, port=parsed.port, name=name, source=source,
        params={"username": username, "password": password, "version": version},
    )


def _parse_tuic(raw: str, source: str) -> Optional[ProxyConfig]:
    parsed = urlparse(raw)
    if not parsed.hostname or not parsed.port:
        return None
    qs = _qs(parsed.query)
    name = unquote(parsed.fragment) if parsed.fragment else f"{parsed.hostname}:{parsed.port}"
    return ProxyConfig(
        raw=raw, protocol="tuic",
        server=parsed.hostname, port=parsed.port, name=name, source=source,
        params={
            "uuid":               unquote(parsed.username or ""),
            "password":           unquote(parsed.password or ""),
            "sni":                qs.get("sni", ""),
            "alpn":               qs.get("alpn", "h3"),
            "congestion_control": qs.get("congestion_control", "bbr"),
            "insecure":           qs.get("allow_insecure", "0"),
        },
    )


def _qs(query: str) -> dict:
    return {k: v[0] if v else "" for k, v in parse_qs(query, keep_blank_values=True).items()}
