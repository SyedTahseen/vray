

def _stream_settings(parsed: dict) -> dict:
    network = parsed.get("network") or "tcp"
    stream = {"network": network}

    if network == "ws":
        stream["wsSettings"] = {
            "path": parsed.get("path") or "/",
            "headers": {"Host": parsed.get("ws_host") or parsed.get("sni") or parsed.get("server", "")},
        }
    elif network == "grpc":
        stream["grpcSettings"] = {"serviceName": parsed.get("service_name") or ""}
    elif network == "h2" or network == "http":
        stream["network"] = "h2"
        stream["httpSettings"] = {
            "path": parsed.get("path") or "/",
            "host": [parsed.get("ws_host") or parsed.get("sni") or parsed.get("server", "")],
        }

    if parsed.get("tls") or parsed.get("security") == "reality":
        if parsed.get("security") == "reality":
            stream["security"] = "reality"
            stream["realitySettings"] = {
                "serverName": parsed.get("sni") or parsed.get("server", ""),
                "fingerprint": parsed.get("fingerprint") or "chrome",
                "password": parsed.get("public_key") or "",
                "publicKey": parsed.get("public_key") or "",
                "shortId": parsed.get("short_id") or "",
            }
        else:
            stream["security"] = "tls"
            stream["tlsSettings"] = {
                "serverName": parsed.get("sni") or parsed.get("server", ""),
                "fingerprint": parsed.get("fingerprint") or "chrome",
            }
            if parsed.get("alpn"):
                stream["tlsSettings"]["alpn"] = [a.strip() for a in parsed["alpn"].split(",") if a.strip()]

    return stream


def _is_reality_config_valid(parsed: dict) -> bool:
    return bool(parsed.get("public_key"))


def build_ss(parsed: dict) -> dict | None:
    method = parsed.get("method")
    password = parsed.get("password")
    if not method or password is None:
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
    uuid = parsed.get("uuid")
    if not uuid:
        return None
    if parsed.get("security") == "reality" and not _is_reality_config_valid(parsed):
        return None
    return {
        "protocol": "vmess",
        "settings": {
            "vnext": [{
                "address": parsed["server"],
                "port": parsed["port"],
                "users": [{
                    "id": uuid,
                    "alterId": parsed.get("alter_id", 0),
                    "security": parsed.get("cipher") or "auto",
                }],
            }]
        },
        "streamSettings": _stream_settings(parsed),
    }


def build_vless(parsed: dict) -> dict | None:
    uuid = parsed.get("uuid_or_password")
    if not uuid:
        return None
    if parsed.get("security") == "reality" and not _is_reality_config_valid(parsed):
        return None
    user = {"id": uuid, "encryption": "none"}
    if parsed.get("flow"):
        user["flow"] = parsed["flow"]
    return {
        "protocol": "vless",
        "settings": {
            "vnext": [{
                "address": parsed["server"],
                "port": parsed["port"],
                "users": [user],
            }]
        },
        "streamSettings": _stream_settings(parsed),
    }


def build_trojan(parsed: dict) -> dict | None:
    password = parsed.get("uuid_or_password")
    if not password:
        return None
    return {
        "protocol": "trojan",
        "settings": {
            "servers": [{
                "address": parsed["server"],
                "port": parsed["port"],
                "password": password,
            }]
        },
        "streamSettings": _stream_settings({**parsed, "tls": parsed.get("tls", True)}),
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
        outbound = builder(parsed)
    except Exception:
        return None
    if outbound is not None:
        outbound["tag"] = "proxy"
    return outbound
