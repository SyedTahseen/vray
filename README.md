# V2Ray verified-proxy bot

Telegram bot that downloads a public proxy list, tests every entry (TCP, then a strict TCP/HTTP
test through Xray), keeps the working ones in SQLite, and publishes them as a base64
subscription file in a GitHub repo. UDP is not tested.

## Layout

```
app/
  main.py          start-up and background loops
  config.py        settings (env vars with defaults)
  database.py      SQLite storage
  subscription.py  builds the subscription list and link
  publisher.py     commits sub.txt to GitHub
  bot/handlers.py  Telegram commands: /start, /subscription, /top
  bot/formatting.py  message splitting helpers
  checker/         fetch, parse, test and geolocate proxies
Dockerfile
.env.example
```

Run locally: `pip install -r requirements.txt && python -m app`

## Settings

Set these in Coolify (or a local `.env`). Everything else has a default.

| Variable | Required | What it is |
| --- | --- | --- |
| `BOT_TOKEN` | yes | Token from @BotFather |
| `GITHUB_REPO` | yes | Repo the subscription is published to, `owner/name` |
| `GITHUB_TOKEN` | yes | Fine-grained token, Contents: Read and write, on that repo only |
| `GITHUB_RAW_URL` | **yes in practice** | Source list to test (one proxy link per line, or a base64 subscription). The built-in default is only a placeholder |

Optional: `GITHUB_BRANCH` (default `main`), `GITHUB_SUB_PATH` (default `sub.txt`),
`PUBLISH_MIN_INTERVAL_MINUTES` (30) - minimum gap between commits of the subscription file.

Tuning (all optional):

| Variable | Default | Effect |
| --- | --- | --- |
| `FUNCTIONAL_TEST_ATTEMPTS` / `FUNCTIONAL_TEST_MIN_PASSES` | 3 / 2 | A proxy must pass at least 2 of up to 3 probes |
| `FUNCTIONAL_TEST_MAX_LATENCY_MS` | 1000 | Best latency above this fails (0 = off) |
| `FUNCTIONAL_TEST_EXTRA_CHECKS` | true | Also needs a second target (`FUNCTIONAL_TEST_SECOND_URL`, must return 204) and a 500 KB download (`FUNCTIONAL_TEST_DOWNLOAD_URL`, `FUNCTIONAL_TEST_DOWNLOAD_MIN_BYTES`). A check that fails even without a proxy is skipped for that run |
| `REVERIFY_INTERVAL_HOURS` | 1 | Full re-check of the verified list (same strict probe) |
| `RECHECK_FAILING_INTERVAL_MINUTES` | 15 | Re-test of only the proxies that failed a sweep |
| `REVERIFY_MAX_FAILS` | 3 | Failed re-checks in a row before removal. A proxy is hidden from the subscription and `/top` after its first failure |
| `REJECT_COOLDOWN_HOURS` | 6 | How long a failed or removed link is not retried |
| `FUNCTIONAL_TEST_URL` / `FUNCTIONAL_TEST_EXPECTED_STATUS` | gstatic 204 / 204 | Primary probe (change both together) |
| `EXIT_GEO_ENABLED` / `EXIT_GEO_URL` | true / ipwho.is | Flag/country of the real exit IP |

Dead proxies: hidden at the first failed check, rechecked every 15 minutes, removed after 3
failures in a row (about 30 minutes after the first failure) and put into the reject cache so
they cannot flap back in.

## What gets tested

Links are converted to Xray outbounds. Links that current Xray (26.7.11+) refuses or that
this bot cannot represent are skipped, not reported as dead: unencrypted VLESS/Trojan
(no TLS/REALITY), VMess `none`/`zero`, Shadowsocks `none`/`plain` or with a plugin, and the
`h2`, `kcp` and `quic` transports. `allowInsecure` is ignored (Xray no longer honours it), so
servers with self-signed certificates fail the test.

The Xray version is pinned in the Dockerfile (`v26.11.9`); change it with
`--build-arg XRAY_VERSION=<tag>` (or `latest`). The download is checked against the release's
`.dgst` SHA-256, and the build fails if it does not match.

## GitHub publishing

1. Create a **separate public** repo (e.g. `vray-sub`) with a `main` branch.
2. Create a fine-grained token for that repo only, with **Contents: Read and write**.
3. The bot commits `sub.txt` only when the *set* of links changes (re-sorting alone does not
   commit), at most once per `PUBLISH_MIN_INTERVAL_MINUTES`. If a re-check sweep removes every
   proxy, the file is emptied instead of serving dead links.
   The link is `https://raw.githubusercontent.com/owner/vray-sub/main/sub.txt`.

## Deploy on Coolify

- Build pack: Dockerfile. Turn **"Is your application a bot?"** on (no domain or port needed).
- Add a persistent volume with destination `/data` so the database survives redeploys.

## Privacy and limits

- The subscription file is **public**: anyone with the link can use the listed servers.
- Location uses `ip-api.com` (HTTP, free tier) for the server IP and `EXIT_GEO_URL` through each
  proxy for its exit IP, so the geo provider sees those exit IPs. If the exit lookup fails, the
  server-IP location is kept, which can be wrong for CDN-fronted proxies.
- Proxies are tested from this server's network, not from your users' ISPs.
- WebSocket and gRPC links still work, but Xray now recommends XHTTP and warns about both.

## Tests

```
python tests/test_parser.py
python tests/test_database.py
python tests/test_functional_logic.py
python tests/test_publisher.py
python tests/test_config_and_format.py
XRAY_BIN_PATH=/usr/local/bin/xray python tests/xray_config_check.py   # optional, needs Xray
```
