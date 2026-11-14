import asyncio, base64, os, sys, types
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.update(GITHUB_TOKEN="t", GITHUB_REPO="owner/repo")
for name in ("aiosqlite", "aiohttp_socks"):
    if name not in sys.modules:
        try: __import__(name)
        except ImportError: sys.modules[name] = types.SimpleNamespace(ProxyConnector=None, connect=None)

repo = {"content": None, "puts": 0}


class Resp:
    def __init__(self, status, data=None): self.status, self._data = status, data
    async def json(self): return self._data
    async def text(self): return ""
    async def __aenter__(self): return self
    async def __aexit__(self, *a): pass


class Session:
    def __init__(self, *a, **k): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): pass
    def get(self, url, params=None):
        return Resp(404) if repo["content"] is None else Resp(200, {"sha": "abc", "content": repo["content"]})
    def put(self, url, json=None):
        repo["puts"] += 1
        repo["content"] = json["content"]
        return Resp(200)


sys.modules["aiohttp"] = types.SimpleNamespace(ClientSession=Session, ClientTimeout=lambda **k: None)
from app import publisher as p

current_links: list[str] = []
async def fake_links(limit): return list(current_links)
p.get_links = fake_links
A, B = "vless://a@1.1.1.1:443?security=tls#x", "trojan://b@2.2.2.2:443#y"


def file_links():
    raw_file = base64.b64decode(repo["content"]).decode()
    return base64.b64decode(raw_file).decode().splitlines() if raw_file else []


def reset(links, content=None):
    repo.update(content=content, puts=0)
    p._last_commit = None
    current_links[:] = links


async def run():
    reset([A, B]); await p.publish_subscription()
    assert repo["puts"] == 1 and file_links() == [A, B]

    await p.publish_subscription(); current_links[:] = [B, A]; p._last_commit = None
    await p.publish_subscription()
    assert repo["puts"] == 1

    current_links[:] = [A]; p._last_commit = None
    await p.publish_subscription()
    assert repo["puts"] == 2 and file_links() == [A]
    current_links[:] = [A, B]
    await p.publish_subscription()
    assert repo["puts"] == 2
    p._last_commit = None; await p.publish_subscription()
    assert repo["puts"] == 3 and file_links() == [A, B]

    reset([], content=repo["content"]); await p.publish_subscription()
    assert repo["puts"] == 0 and file_links() == [A, B]
    await p.publish_subscription(allow_empty=True)
    assert repo["puts"] == 1 and file_links() == []
    await p.publish_subscription(allow_empty=True)
    assert repo["puts"] == 1
    reset([]); await p.publish_subscription(allow_empty=True)
    assert repo["puts"] == 0
    print("publisher tests: ALL PASSED")

asyncio.run(run())
