import base64, json, sys
import os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.checker.parser import apply_remark, dedupe_by_identity, identity_key, link_key, parse_bulk, parse_line
from app.checker.xray_outbound import build_outbound

def b64(s): return base64.b64encode(s.encode()).decode()
def ob(link): 
    p = parse_line(link); assert p, link
    return p, build_outbound(p)

p, o = ob("trojan://pass@example.com:443?type=tcp#t")
assert p["tls"] and o["streamSettings"]["security"] == "tls", o
p, o = ob("trojan://pass@example.com:80?security=none#t"); assert o is None
assert ob("vless://u-u-i-d@1.2.3.4:80?type=ws&path=/a#x")[1] is None
p, o = ob("vless://uuid@1.2.3.4:443?security=tls&type=ws&host=cdn.example.com&path=%2Fws%3Fed%3D2048#x")
assert p["sni"] == "cdn.example.com", p["sni"]
assert o["streamSettings"]["wsSettings"]["path"] == "/ws?ed=2048"
assert o["streamSettings"]["tlsSettings"]["serverName"] == "cdn.example.com"
p, o = ob("vless://uuid@1.2.3.4:443?security=reality&pbk=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA&sid=ab&sni=www.x.com&flow=xtls-rprx-vision&fp=chrome#r")
rs = o["streamSettings"]["realitySettings"]
assert rs["password"] == "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" and "publicKey" not in rs and rs["serverName"] == "www.x.com"
assert o["settings"]["vnext"][0]["users"][0]["flow"] == "xtls-rprx-vision"
assert ob("vless://uuid@1.2.3.4:443?security=reality&pbk=K&type=ws#r")[1] is None
assert ob("vless://uuid@1.2.3.4:443?security=reality&type=tcp#r")[1] is None
vm = {"v":"2","ps":"n","add":"h.example.com","port":"443","id":"uuid","aid":"0","net":"grpc","path":"mysvc","tls":"tls","scy":"auto"}
p, o = ob("vmess://" + b64(json.dumps(vm)))
assert o["streamSettings"]["grpcSettings"]["serviceName"] == "mysvc", o
assert ob("vmess://" + b64(json.dumps({**vm, "scy":"none"})))[1] is None
assert ob("vmess://" + b64(json.dumps({**vm, "net":"h2"})))[1] is None
assert ob("vmess://" + b64(json.dumps({**vm, "net":"kcp"})))[1] is None
assert ob("vmess://" + b64(json.dumps({**vm, "net":"tcp","tls":""})))[1] is not None
p, o = ob("ss://" + b64("aes-256-gcm:pw") + "@1.1.1.1:8388#a")
assert (p["method"], p["password"], p["server"], p["port"]) == ("aes-256-gcm","pw","1.1.1.1",8388)
p, o = ob("ss://2022-blake3-aes-128-gcm:AAAA%2BBBB%3D%3D@2.2.2.2:443#b")
assert p["method"] == "2022-blake3-aes-128-gcm" and p["password"] == "AAAA+BBB==", p
p, o = ob("ss://" + b64("aes-128-gcm:pw") + "@[2001:db8::1]:8388/?x=1#c")
assert p["server"] == "2001:db8::1" and p["port"] == 8388
p, o = ob("ss://" + b64("aes-128-gcm:pw@3.3.3.3:9999") + "#legacy")
assert p["server"] == "3.3.3.3" and p["port"] == 9999
assert ob("ss://" + b64("aes-128-gcm:pw") + "@1.1.1.1:8388/?plugin=obfs-local%3Bobfs%3Dhttp#p")[1] is None
assert ob("ss://" + b64("none:pw") + "@1.1.1.1:8388#n")[1] is None
plain = "\ufeffvless://uuid@1.2.3.4:443?security=tls#a\ntrojan://p@h.com:443#b\nrubbish\n"
assert len(parse_bulk(plain)) == 2
assert len(parse_bulk(b64(plain.lstrip("\ufeff")))) == 2
l = "vless://uuid@1.2.3.4:443?security=tls#old"
assert apply_remark(l, "vless", "🇩🇪 vless-DE 🔒").startswith("vless://uuid@1.2.3.4:443?security=tls#")
o = ob("vless://uuid@1.2.3.4:443?security=tls&type=xhttp&path=/x&mode=auto&extra=%7B%22a%22%3A1%7D#x")[1]
assert o["streamSettings"]["xhttpSettings"]["extra"] == {"a": 1}
assert ob("vless://uuid@1.2.3.4:443?security=tls&type=httpupgrade&path=/h#x")[1]["streamSettings"]["network"] == "httpupgrade"

K = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
p, o = ob("trojan://ab:cd@example.com:443?security=tls#t")
assert p["secret"] == "ab:cd" and o["settings"]["servers"][0]["password"] == "ab:cd"
for bad in ("aes-256-cfb", "rc4-md5", "chacha20-ietf", "aes-128-ctr"):
    assert ob("ss://" + b64(bad + ":pw") + "@1.1.1.1:8388#a")[1] is None, bad
for good in ("aes-128-gcm", "aes-256-gcm", "chacha20-ietf-poly1305", "xchacha20-poly1305"):
    assert ob("ss://" + b64(good + ":pw") + "@1.1.1.1:8388#a")[1] is not None, good
key16, key32 = base64.b64encode(b"x" * 16).decode(), base64.b64encode(b"y" * 32).decode()
def ss22(method, pw): return ob("ss://" + b64(method + ":" + pw) + "@2.2.2.2:443#b")[1]
assert ss22("2022-blake3-aes-128-gcm", key16) is not None
assert ss22("2022-blake3-aes-256-gcm", key32) is not None
assert ss22("2022-blake3-aes-256-gcm", key16) is None
assert ss22("2022-blake3-aes-256-gcm", "notbase64!!") is None
assert ss22("2022-blake3-aes-256-gcm", key32 + ":" + key32) is not None
base = "vless://uuid@1.2.3.4:443?security=reality&sni=x.com&flow=xtls-rprx-vision&pbk="
assert ob(base + K + "&sid=ab12")[1] is not None
assert ob(base + K + "&sid=abc")[1] is None
assert ob(base + K + "&sid=zz")[1] is None
assert ob(base + K + "&sid=" + "ab" * 9)[1] is None
assert ob(base + "tooshort&sid=ab")[1] is None
o = ob(base + K + "&sid=ab&spx=%2Fx&pqv=PQ")[1]["streamSettings"]["realitySettings"]
assert o["spiderX"] == "/x" and o["mldsa65Verify"] == "PQ"
assert ob("vless://uuid@1.2.3.4:443?security=tls&fp=notafp#a")[1] is None
assert ob("vless://uuid@1.2.3.4:443?security=tls&fp=firefox#a")[1] is not None
assert ob("vless://uuid@1.2.3.4:443?security=tls&type=ws&flow=xtls-rprx-vision#a")[1] is None
assert ob("vless://uuid@1.2.3.4:443?security=tls&type=tcp&flow=xtls-rprx-vision#a")[1] is not None
assert ob("vless://uuid@1.2.3.4:443?security=tls&flow=bogus#a")[1] is None
o = ob("vless://uuid@1.2.3.4:443?security=tls&alpn=h2,junk,http/1.1#a")[1]
assert o["streamSettings"]["tlsSettings"]["alpn"] == ["h2", "http/1.1"]
assert ob("vmess://" + b64(json.dumps({**vm, "scy": "aes-128-cfb"})))[1] is None
assert ob("vmess://" + b64(json.dumps({**vm, "scy": "chacha20-poly1305"})))[1] is not None
pin = "ab" * 32
o = ob("vless://uuid@1.2.3.4:443?security=tls&pcs=" + pin + "&vcn=real.example.com&ech=ECHCFG#a")[1]["streamSettings"]
assert o["tlsSettings"]["pinnedPeerCertSha256"] == pin
assert o["tlsSettings"]["verifyPeerCertByName"] == "real.example.com"
assert o["tlsSettings"]["echConfigList"] == "ECHCFG"
assert ob("vless://uuid@1.2.3.4:443?security=tls&pcs=nothex#a")[1] is None
o = ob("vless://uuid@1.2.3.4:443?security=tls&fm=%7B%22udp%22%3A%5B%5D%7D#a")[1]["streamSettings"]
assert o["finalmask"] == {"udp": []}
assert ob("vless://uuid@1.2.3.4:443?security=tls&fm=notjson#a")[1] is None
assert link_key("vless://u@h:443?security=tls#one") == link_key("vless://u@h:443?security=tls#two")
assert link_key("vless://u@h:443?security=tls#x") != link_key("vless://u@h:444?security=tls#x")
v1, v2 = {**vm, "ps": "A"}, {**vm, "ps": "B"}
assert link_key("vmess://" + b64(json.dumps(v1))) == link_key("vmess://" + b64(json.dumps(v2)))
print("parser/outbound tests: ALL PASSED")


_a = parse_line("vless://11111111-1111-1111-1111-111111111111@172.67.1.1:443?security=tls&type=ws&path=%2Fa&host=a.example.com#a")
_b = parse_line("vless://22222222-2222-2222-2222-222222222222@172.67.1.1:443?security=tls&type=ws&path=%2Fb&host=b.example.com#b")
_a2 = parse_line("vless://11111111-1111-1111-1111-111111111111@172.67.1.1:443?type=ws&host=a.example.com&path=%2Fa&security=tls#renamed")
assert len(dedupe_by_identity([_a, _b], set())) == 2
assert len(dedupe_by_identity([_a, _a2], set())) == 1
assert dedupe_by_identity([_a, _b], {identity_key(_a)}) == [_b]
_u = "vless://11111111-1111-1111-1111-111111111111@h.example.com:443?security=tls&type=ws&path=%2F&host=h.example.com&fp=unsafe"
assert build_outbound(parse_line(_u))["streamSettings"]["tlsSettings"]["fingerprint"] == "unsafe"
_r = "vless://11111111-1111-1111-1111-111111111111@h.example.com:443?security=reality&type=tcp&fp=unsafe&pbk=" + "A" * 43 + "&sid=ab"
assert build_outbound(parse_line(_r)) is None
print("dedupe/fingerprint tests: ALL PASSED")

_vm = {"v": "2", "ps": "x", "add": "a.example.com", "port": "443", "id": "11111111-1111-1111-1111-111111111111",
       "aid": "0", "net": "tcp", "type": "none", "tls": "reality", "sni": "www.example.com", "fp": "chrome"}
assert parse_line("vmess://" + base64.b64encode(json.dumps(_vm).encode()).decode())["security"] == "reality"
assert build_outbound(parse_line("vmess://" + base64.b64encode(json.dumps(_vm).encode()).decode())) is None
_vm["tls"] = "tls"
assert build_outbound(parse_line("vmess://" + base64.b64encode(json.dumps(_vm).encode()).decode()))["streamSettings"]["security"] == "tls"

_rl = "vless://11111111-1111-1111-1111-111111111111@h.example.com:443?security=reality&type=tcp&flow=xtls-rprx-vision&pbk=" + "A" * 43 + "&sid=ab"
_rs = build_outbound(parse_line(_rl))["streamSettings"]["realitySettings"]
assert "password" in _rs and "publicKey" not in _rs
print("vmess/reality field tests: ALL PASSED")
