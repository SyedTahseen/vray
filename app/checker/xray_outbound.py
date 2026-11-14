import base64
import json
import re

from app.checker.parser import b64_pad

_NETWORK_ALIASES = {"tcp": "tcp", "raw": "tcp", "ws": "ws", "websocket": "ws", "grpc": "grpc",
                    "httpupgrade": "httpupgrade", "xhttp": "xhttp", "splithttp": "xhttp"}
_REALITY_NETWORKS = {"tcp", "grpc", "xhttp"}

_VMESS_CIPHERS = {"auto", "aes-128-gcm", "chacha20-poly1305"}
_SS_CLASSIC = {"aes-128-gcm", "aes-256-gcm", "chacha20-poly1305", "chacha20-ietf-poly1305",
               "xchacha20-poly1305", "xchacha20-ietf-poly1305"}
_SS_2022 = {"2022-blake3-aes-128-gcm": {16, 32}, "2022-blake3-aes-256-gcm": {32},
            "2022-blake3-chacha20-poly1305": {32}}
_FINGERPRINTS = {"chrome", "firefox", "safari", "ios", "android", "edge", "360", "qq",
                 "random", "randomized", "randomizednoalpn"}
_ALPNS = {"h2", "http/1.1", "h3"}
_FLOWS = {"", "none", "xtls-rprx-vision", "xtls-rprx-vision-udp443"}
_SHORT_ID_RE = re.compile(r"^([0-9a-fA-F]{2}){0,8}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _b64_len(value: str) -> int | None:
    try:
        return len(base64.b64decode(b64_pad(value), validate=True))
    except Exception:
        return None


def _valid_fingerprint(fp: str, reality: bool) -> bool:
    low = fp.lower()
    if low == "unsafe":
        return not reality
    if low in _FINGERPRINTS:
        return True
    return not reality and fp.startswith("Hello")


def _normalize_pins(value: str) -> str | None:
    pins = [v.replace(":", "").strip().lower() for v in value.split(",") if v.strip()]
    if not pins or not all(_SHA256_RE.match(p) for p in pins):
        return None
    return ",".join(pins)


def _split(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _stream_settings(parsed: dict) -> dict | None:
    network = _NETWORK_ALIASES.get((parsed.get("network") or "tcp").lower())
    if network is None:
        return None

    security = parsed.get("security") or ("tls" if parsed.get("tls") else "none")
    if security not in ("none", "tls", "reality"):
        return None
    if security == "reality" and network not in _REALITY_NETWORKS:
        return None

    server_name = parsed.get("sni") or parsed["server"]
    host = parsed.get("ws_host") or server_name
    path = parsed.get("path") or "/"
    stream: dict = {"network": network}

    if network == "tcp" and parsed.get("header_type") == "http":
        stream["tcpSettings"] = {"header": {"type": "http", "request": {
            "path": _split(path) or ["/"],
            "headers": {"Host": _split(parsed.get("ws_host") or "") or [host]},
        }}}
    elif network == "ws":
        stream["wsSettings"] = {"path": path, "headers": {"Host": host}}
    elif network == "httpupgrade":
        stream["httpupgradeSettings"] = {"path": path, "host": host}
    elif network == "grpc":
        grpc = {"serviceName": parsed.get("service_name") or "",
                "multiMode": parsed.get("mode") == "multi"}
        if parsed.get("authority"):
            grpc["authority"] = parsed["authority"]
        stream["grpcSettings"] = grpc
    elif network == "xhttp":
        xhttp = {"path": path, "host": host}
        if parsed.get("mode"):
            xhttp["mode"] = parsed["mode"]
        if parsed.get("extra"):
            try:
                extra = json.loads(parsed["extra"])
            except ValueError:
                return None
            if isinstance(extra, dict):
                xhttp["extra"] = extra
        stream["xhttpSettings"] = xhttp

    fingerprint = parsed.get("fingerprint") or "chrome"
    if not _valid_fingerprint(fingerprint, reality=security == "reality"):
        return None

    if security == "reality":
        public_key = parsed.get("public_key") or ""
        if _b64_len(public_key) != 32:
            return None
        short_id = parsed.get("short_id") or ""
        if not _SHORT_ID_RE.match(short_id):
            return None
        reality = {
            "serverName": server_name,
            "fingerprint": fingerprint,
            "password": public_key,
            "shortId": short_id,
        }
        if parsed.get("spider_x"):
            reality["spiderX"] = parsed["spider_x"]
        if parsed.get("mldsa65_verify"):
            reality["mldsa65Verify"] = parsed["mldsa65_verify"]
        stream["security"] = "reality"
        stream["realitySettings"] = reality
    elif security == "tls":
        tls_settings = {"serverName": server_name, "fingerprint": fingerprint}
        alpn = [a for a in _split(parsed.get("alpn") or "") if a in _ALPNS]
        if alpn:
            tls_settings["alpn"] = alpn
        if parsed.get("pin_sha256"):
            pins = _normalize_pins(parsed["pin_sha256"])
            if pins is None:
                return None
            tls_settings["pinnedPeerCertSha256"] = pins
        if parsed.get("verify_name"):
            tls_settings["verifyPeerCertByName"] = parsed["verify_name"]
        if parsed.get("ech"):
            tls_settings["echConfigList"] = parsed["ech"]
        stream["security"] = "tls"
        stream["tlsSettings"] = tls_settings

    if parsed.get("finalmask"):
        try:
            mask = json.loads(parsed["finalmask"])
        except ValueError:
            return None
        if not isinstance(mask, dict):
            return None
        stream["finalmask"] = mask

    return stream


def _is_encrypted_transport(stream: dict) -> bool:
    return stream.get("security") in ("tls", "reality")


def _valid_ss_method(method: str, password: str) -> bool:
    if method in _SS_CLASSIC:
        return bool(password)
    key_sizes = _SS_2022.get(method)
    if key_sizes is None:
        return False
    return all(_b64_len(part) in key_sizes for part in password.split(":"))


def build_ss(parsed: dict) -> dict | None:
    method = (parsed.get("method") or "").lower()
    password = parsed.get("password")
    if password is None or parsed.get("plugin") or not _valid_ss_method(method, password):
        return None
    return {
        "protocol": "shadowsocks",
        "settings": {
            "servers": [{
                "address": parsed["server"],
                "port": parsed["port"],
                "method": method,
                "password": password,
            }]
        },
    }


def build_vmess(parsed: dict) -> dict | None:
    cipher = (parsed.get("cipher") or "auto").lower()
    if not parsed.get("secret") or cipher not in _VMESS_CIPHERS:
        return None
    stream = _stream_settings(parsed)
    if stream is None:
        return None
    return {
        "protocol": "vmess",
        "settings": {
            "vnext": [{
                "address": parsed["server"],
                "port": parsed["port"],
                "users": [{
                    "id": parsed["secret"],
                    "alterId": parsed.get("alter_id", 0),
                    "security": cipher,
                }],
            }]
        },
        "streamSettings": stream,
    }


def build_vless(parsed: dict) -> dict | None:
    if not parsed.get("secret"):
        return None
    stream = _stream_settings(parsed)
    if stream is None:
        return None
    encryption = parsed.get("encryption") or "none"
    if encryption == "none" and not _is_encrypted_transport(stream):
        return None
    flow = (parsed.get("flow") or "").lower()
    if flow not in _FLOWS:
        return None
    user = {"id": parsed["secret"], "encryption": encryption}
    if flow not in ("", "none"):
        if encryption == "none" and not (stream.get("network") == "tcp" and _is_encrypted_transport(stream)):
            return None
        user["flow"] = flow
    return {
        "protocol": "vless",
        "settings": {
            "vnext": [{
                "address": parsed["server"],
                "port": parsed["port"],
                "users": [user],
            }]
        },
        "streamSettings": stream,
    }


def build_trojan(parsed: dict) -> dict | None:
    if not parsed.get("secret"):
        return None
    stream = _stream_settings(parsed)
    if stream is None or not _is_encrypted_transport(stream):
        return None
    return {
        "protocol": "trojan",
        "settings": {
            "servers": [{
                "address": parsed["server"],
                "port": parsed["port"],
                "password": parsed["secret"],
            }]
        },
        "streamSettings": stream,
    }


_BUILDERS = {
    "ss": build_ss,
    "vmess": build_vmess,
    "vless": build_vless,
    "trojan": build_trojan,
}


def build_outbound(parsed: dict) -> dict | None:
    builder = _BUILDERS.get(parsed.get("protocol"))
    if not builder:
        return None
    try:
        return builder(parsed)
    except Exception:
        return None
