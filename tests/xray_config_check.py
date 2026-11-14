import base64, json, os, shutil, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.checker.parser import parse_line
from app.checker.xray_outbound import build_outbound

XRAY = os.getenv("XRAY_BIN_PATH") or shutil.which("xray")
if not XRAY or not os.path.exists(XRAY):
    print("xray binary not found - skipped"); sys.exit(0)

UUID, PBK = "11111111-1111-1111-1111-111111111111", "A" * 43
vmess = {"v": "2", "ps": "x", "add": "h.example.com", "port": "443", "id": UUID, "aid": "0", "net": "ws",
         "host": "h.example.com", "path": "/", "tls": "tls"}
LINKS = [
    f"vless://{UUID}@h.example.com:443?security=tls&type=ws&path=%2F&host=h.example.com#ws",
    f"vless://{UUID}@h.example.com:443?security=tls&type=grpc&serviceName=s&mode=multi#grpc",
    f"vless://{UUID}@h.example.com:443?security=tls&type=xhttp&path=%2F&mode=auto#xhttp",
    f"vless://{UUID}@h.example.com:443?security=reality&type=tcp&flow=xtls-rprx-vision&pbk={PBK}&sid=ab&sni=www.example.com#reality",
    f"trojan://pass@h.example.com:443?security=tls&type=tcp#trojan",
    "vmess://" + base64.b64encode(json.dumps(vmess).encode()).decode(),
    "ss://" + base64.b64encode(b"aes-256-gcm:password").decode() + "@h.example.com:8388#ss",
]
failed = 0
for link in LINKS:
    outbound = build_outbound(parse_line(link))
    assert outbound is not None, f"builder rejected {link[:40]}"
    config = {"inbounds": [], "outbounds": [{**outbound, "tag": "out"}]}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(config, f)
    r = subprocess.run([XRAY, "run", "-test", "-c", f.name], capture_output=True, text=True)
    os.remove(f.name)
    ok = r.returncode == 0
    failed += not ok
    print(("OK   " if ok else "FAIL ") + link.split("://")[0], "" if ok else (r.stdout + r.stderr)[-300:])
sys.exit(1 if failed else 0)
