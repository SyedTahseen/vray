import base64
import json
import re
from urllib.parse import urlparse, unquote, quote, parse_qs

_B64_PAD = re.compile(r"^[A-Za-z0-9+/_-]+={0,2}$")


def _b64_decode(data: str) -> str:
    data = data.strip()
    data = data.replace("-", "+").replace("_", "/")
    missing_padding = len(data) % 4
    if missing_padding:
        data += "=" * (4 - missing_padding)
    return base64.b64decode(data).decode("utf-8", errors="ignore")


def parse_ss(link: str) -> dict | None:
    try:
        body = link[len("ss://"):]
        remark = ""
        if "#" in body:
            body, frag = body.split("#", 1)
            remark = unquote(frag)

        if "@" in body:
            userinfo_b64, hostport = body.rsplit("@", 1)
            host, port = hostport.rsplit(":", 1)
            port = int(port.split("/")[0].split("?")[0])
            method, password = _b64_decode(userinfo_b64).split(":", 1)
            return {
                "raw_link": link.strip(),
                "protocol": "ss",
                "server": host.strip(),
                "port": port,
                "remark": remark,
                "tls": False,
                "method": method.strip(),
                "password": password.strip(),
            }
        else:
            decoded = _b64_decode(body)
            methodpass, hostpart = decoded.rsplit("@", 1)
            method, password = methodpass.split(":", 1)
            host, port = hostpart.rsplit(":", 1)
            return {
                "raw_link": link.strip(),
                "protocol": "ss",
                "server": host.strip(),
                "port": int(port),
                "remark": remark,
                "tls": False,
                "method": method.strip(),
                "password": password.strip(),
            }
    except Exception:
        return None


def parse_vmess(link: str) -> dict | None:
    try:
        body = link[len("vmess://"):].strip()
        decoded = _b64_decode(body)
        data = json.loads(decoded)
        remark = data.get("ps", "")
        host = str(data.get("add", "")).strip()
        port = int(str(data.get("port", 0)).strip())
        if not host or not port:
            return None
        tls = str(data.get("tls", "")).strip().lower() in ("tls", "reality")
        return {
            "raw_link": link.strip(),
            "protocol": "vmess",
            "server": host,
            "port": port,
            "remark": remark,
            "tls": tls,
            "uuid": str(data.get("id", "")).strip(),
            "alter_id": int(str(data.get("aid", 0)).strip() or 0),
            "cipher": str(data.get("scy") or data.get("security") or "auto").strip(),
            "network": str(data.get("net", "tcp")).strip().lower() or "tcp",
            "header_type": str(data.get("type", "")).strip().lower(),
            "ws_host": str(data.get("host", "")).strip(),
            "path": str(data.get("path", "")).strip(),
            "sni": str(data.get("sni", "")).strip() or host,
            "alpn": str(data.get("alpn", "")).strip(),
            "fingerprint": str(data.get("fp", "")).strip(),
        }
    except Exception:
        return None


def parse_vless_or_trojan(link: str, protocol: str) -> dict | None:
    try:
        parsed = urlparse(link.strip())
        host = parsed.hostname
        port = parsed.port
        if not host or not port:
            return None
        remark = unquote(parsed.fragment) if parsed.fragment else ""
        qs = parse_qs(parsed.query)

        def q(key, default=""):
            return (qs.get(key, [default])[0] or default).strip()

        security = q("security").lower()
        tls = security in ("tls", "reality")
        return {
            "raw_link": link.strip(),
            "protocol": protocol,
            "server": host,
            "port": int(port),
            "remark": remark,
            "tls": tls,
            "uuid_or_password": unquote(parsed.username or ""),
            "network": q("type", "tcp").lower() or "tcp",
            "path": unquote(q("path")),
            "ws_host": q("host"),
            "sni": q("sni") or q("peer") or host,
            "alpn": q("alpn"),
            "fingerprint": q("fp"),
            "flow": q("flow"),
            "service_name": q("serviceName"),
            "security": security,
            "public_key": q("pbk"),
            "short_id": q("sid"),
        }
    except Exception:
        return None


def parse_line(line: str) -> dict | None:
    line = line.strip()
    if not line:
        return None
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
            body = raw_link[len("vmess://"):].strip()
            decoded = _b64_decode(body)
            data = json.loads(decoded)
            data["ps"] = new_remark
            new_body = base64.b64encode(
                json.dumps(data, separators=(",", ":")).encode("utf-8")
            ).decode("utf-8")
            return f"vmess://{new_body}"
        else:
            base = raw_link.split("#", 1)[0]
            return f"{base}#{quote(new_remark)}"
    except Exception:
        return raw_link


def parse_bulk(text: str) -> list[dict]:
    results = []
    for line in text.splitlines():
        parsed = parse_line(line)
        if parsed:
            results.append(parsed)
    return results
