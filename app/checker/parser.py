import base64
import json
from urllib.parse import parse_qs, quote, unquote, urlparse


def b64_pad(data: str) -> str:
    data = data.strip().replace("-", "+").replace("_", "/")
    return data + "=" * (-len(data) % 4)


def _b64_decode(data: str) -> str:
    return base64.b64decode(b64_pad(data)).decode("utf-8", errors="ignore")


def parse_ss(link: str) -> dict | None:
    try:
        body = link[len("ss://"):].partition("#")[0]
        if "@" in body:
            userinfo, hostport = body.rsplit("@", 1)
            plain = unquote(userinfo)
            credentials = plain if ":" in plain else _b64_decode(userinfo)
        else:
            credentials, hostport = _b64_decode(body.split("?", 1)[0].rstrip("/")).rsplit("@", 1)

        hostport, _, query = hostport.partition("?")
        hostport = hostport.split("/")[0]
        host, port = hostport.rsplit(":", 1)
        method, password = credentials.split(":", 1)
        plugin = (parse_qs(query).get("plugin") or [""])[0]
        return {
            "raw_link": link.strip(),
            "protocol": "ss",
            "server": host.strip().strip("[]"),
            "port": int(port),
            "tls": False,
            "method": method.strip(),
            "password": password.strip(),
            "plugin": plugin,
        }
    except Exception:
        return None


def parse_vmess(link: str) -> dict | None:
    try:
        data = json.loads(_b64_decode(link[len("vmess://"):]))

        def field(key: str, default="") -> str:
            return str(data.get(key, default)).strip()

        host = field("add")
        port = int(field("port", 0))
        if not host or not port:
            return None
        network = field("net", "tcp").lower() or "tcp"
        security = field("tls").lower()
        ws_host = field("host")
        path = field("path")
        return {
            "raw_link": link.strip(),
            "protocol": "vmess",
            "server": host,
            "port": port,
            "tls": security in ("tls", "reality"),
            "security": security if security in ("tls", "reality") else "none",
            "secret": field("id"),
            "alter_id": int(field("aid", 0) or 0),
            "cipher": str(data.get("scy") or data.get("security") or "auto").strip(),
            "network": network,
            "ws_host": ws_host,
            "path": path,
            "service_name": path if network == "grpc" else "",
            "header_type": field("type").lower(),
            "sni": field("sni") or ws_host or host,
            "alpn": field("alpn"),
            "fingerprint": field("fp"),
            "pin_sha256": field("pcs") or field("pinnedPeerCertSha256"),
            "verify_name": field("vcn") or field("verifyPeerCertByName"),
        }
    except Exception:
        return None


def _userinfo(parsed) -> str:
    return unquote(parsed.netloc.rpartition("@")[0])


def parse_vless_or_trojan(link: str, protocol: str) -> dict | None:
    try:
        parsed = urlparse(link.strip())
        host, port = parsed.hostname, parsed.port
        if not host or not port:
            return None
        qs = parse_qs(parsed.query)

        def q(key: str, default: str = "") -> str:
            return (qs.get(key, [default])[0] or default).strip()

        security = q("security").lower() or ("tls" if protocol == "trojan" else "none")
        ws_host = q("host")
        return {
            "raw_link": link.strip(),
            "protocol": protocol,
            "server": host,
            "port": port,
            "tls": security in ("tls", "reality"),
            "secret": _userinfo(parsed),
            "network": q("type", "tcp").lower() or "tcp",
            "path": q("path"),
            "ws_host": ws_host,
            "sni": q("sni") or q("peer") or ws_host or host,
            "alpn": q("alpn"),
            "fingerprint": q("fp"),
            "flow": q("flow"),
            "encryption": q("encryption"),
            "header_type": q("headerType").lower(),
            "service_name": q("serviceName"),
            "authority": q("authority"),
            "mode": q("mode").lower(),
            "extra": q("extra"),
            "security": security,
            "public_key": q("pbk"),
            "short_id": q("sid"),
            "spider_x": q("spx"),
            "mldsa65_verify": q("pqv"),
            "pin_sha256": q("pcs") or q("pinnedPeerCertSha256"),
            "verify_name": q("vcn") or q("verifyPeerCertByName"),
            "ech": q("ech"),
            "finalmask": q("fm"),
        }
    except Exception:
        return None


def parse_line(line: str) -> dict | None:
    line = line.strip().lstrip("\ufeff")
    if line.startswith("ss://"):
        return parse_ss(line)
    if line.startswith("vmess://"):
        return parse_vmess(line)
    if line.startswith("vless://"):
        return parse_vless_or_trojan(line, "vless")
    if line.startswith("trojan://"):
        return parse_vless_or_trojan(line, "trojan")
    return None


def apply_remark(raw_link: str, protocol: str, new_remark: str) -> str:
    try:
        if protocol == "vmess":
            data = json.loads(_b64_decode(raw_link[len("vmess://"):]))
            data["ps"] = new_remark
            encoded = base64.b64encode(json.dumps(data, separators=(",", ":")).encode("utf-8"))
            return f"vmess://{encoded.decode('utf-8')}"
        return f"{raw_link.split('#', 1)[0]}#{quote(new_remark)}"
    except Exception:
        return raw_link


def link_key(raw_link: str) -> str:
    raw_link = raw_link.strip()
    try:
        if raw_link.startswith("vmess://"):
            data = json.loads(_b64_decode(raw_link[len("vmess://"):]))
            data.pop("ps", None)
            return "vmess://" + json.dumps(data, sort_keys=True, separators=(",", ":"))
    except Exception:
        return raw_link
    return raw_link.split("#", 1)[0]


def identity_key(p: dict) -> tuple:
    return (
        p["protocol"], p["server"].lower(), p["port"],
        p.get("secret") or "", p.get("method") or "", p.get("password") or "",
        p.get("network") or "", (p.get("sni") or "").lower(), (p.get("ws_host") or "").lower(),
        p.get("path") or "", p.get("service_name") or "", p.get("security") or "",
        p.get("public_key") or "", p.get("short_id") or "",
    )


def dedupe_by_identity(parsed: list[dict], known: set[tuple]) -> list[dict]:
    seen = set(known)
    unique = []
    for p in parsed:
        key = identity_key(p)
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def _parse_lines(text: str) -> list[dict]:
    return [parsed for line in text.splitlines() if (parsed := parse_line(line))]


def parse_bulk(text: str) -> list[dict]:
    results = _parse_lines(text)
    if results:
        return results
    try:
        return _parse_lines(_b64_decode("".join(text.split())))
    except Exception:
        return []
