import os
import re
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _env(name: str, default):
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    if isinstance(default, bool):
        return raw.strip().lower() in ("1", "true", "yes", "on")
    try:
        if isinstance(default, int):
            return int(raw)
        if isinstance(default, float):
            return float(raw)
    except ValueError:
        raise SystemExit(f"Invalid value for {name}: {raw!r} (expected a number)") from None
    return raw


@dataclass(frozen=True)
class Settings:
    BOT_TOKEN: str = _env("BOT_TOKEN", "")
    GITHUB_RAW_URL: str = _env(
        "GITHUB_RAW_URL",
        "https://raw.githubusercontent.com/example/example-repo/main/V2Ray-Config.txt",
    )

    GITHUB_TOKEN: str = _env("GITHUB_TOKEN", "")
    GITHUB_REPO: str = _env("GITHUB_REPO", "")
    GITHUB_BRANCH: str = _env("GITHUB_BRANCH", "main")
    GITHUB_SUB_PATH: str = _env("GITHUB_SUB_PATH", "sub.txt")

    DB_PATH: str = _env("DB_PATH", "data/v2ray_bot.sqlite3")

    FETCH_INTERVAL_MINUTES: int = _env("FETCH_INTERVAL_MINUTES", 10)
    REVERIFY_INTERVAL_HOURS: float = _env("REVERIFY_INTERVAL_HOURS", 1.0)
    PUBLISH_MIN_INTERVAL_MINUTES: int = _env("PUBLISH_MIN_INTERVAL_MINUTES", 30)
    VERIFIED_FILE_LIMIT: int = _env("VERIFIED_FILE_LIMIT", 1000)

    TCP_TIMEOUT_SECONDS: float = _env("TCP_TIMEOUT_SECONDS", 6.0)
    TEST_CONCURRENCY: int = _env("TEST_CONCURRENCY", 100)
    GEOIP_BATCH_DELAY_SECONDS: float = _env("GEOIP_BATCH_DELAY_SECONDS", 4.2)

    FUNCTIONAL_TEST_ENABLED: bool = _env("FUNCTIONAL_TEST_ENABLED", True)
    XRAY_BIN_PATH: str = _env("XRAY_BIN_PATH", "/usr/local/bin/xray")
    FUNCTIONAL_TEST_URL: str = _env("FUNCTIONAL_TEST_URL", "https://www.gstatic.com/generate_204")
    FUNCTIONAL_TEST_EXPECTED_STATUS: int = _env("FUNCTIONAL_TEST_EXPECTED_STATUS", 204)
    FUNCTIONAL_TEST_TIMEOUT_SECONDS: float = _env("FUNCTIONAL_TEST_TIMEOUT_SECONDS", 10.0)
    FUNCTIONAL_TEST_STARTUP_SECONDS: float = _env("FUNCTIONAL_TEST_STARTUP_SECONDS", 5.0)
    FUNCTIONAL_TEST_CHUNK_SIZE: int = _env("FUNCTIONAL_TEST_CHUNK_SIZE", 100)
    FUNCTIONAL_TEST_CONCURRENCY: int = _env("FUNCTIONAL_TEST_CONCURRENCY", 40)
    FUNCTIONAL_TEST_BATCH_SIZE: int = _env("FUNCTIONAL_TEST_BATCH_SIZE", 300)
    FUNCTIONAL_TEST_ATTEMPTS: int = _env("FUNCTIONAL_TEST_ATTEMPTS", 3)
    FUNCTIONAL_TEST_MIN_PASSES: int = _env("FUNCTIONAL_TEST_MIN_PASSES", 2)
    FUNCTIONAL_TEST_MAX_LATENCY_MS: int = _env("FUNCTIONAL_TEST_MAX_LATENCY_MS", 1000)
    FUNCTIONAL_TEST_EXTRA_CHECKS: bool = _env("FUNCTIONAL_TEST_EXTRA_CHECKS", True)
    FUNCTIONAL_TEST_SECOND_URL: str = _env("FUNCTIONAL_TEST_SECOND_URL", "https://cp.cloudflare.com/generate_204")
    FUNCTIONAL_TEST_DOWNLOAD_URL: str = _env("FUNCTIONAL_TEST_DOWNLOAD_URL", "https://speed.cloudflare.com/__down?bytes=10000000")
    FUNCTIONAL_TEST_DOWNLOAD_MIN_BYTES: int = _env("FUNCTIONAL_TEST_DOWNLOAD_MIN_BYTES", 10000000)
    FUNCTIONAL_TEST_DOWNLOAD_TIMEOUT_SECONDS: float = _env("FUNCTIONAL_TEST_DOWNLOAD_TIMEOUT_SECONDS", 15.0)
    FUNCTIONAL_TEST_DOWNLOAD_CONCURRENCY: int = _env("FUNCTIONAL_TEST_DOWNLOAD_CONCURRENCY", 3)

    EXIT_GEO_ENABLED: bool = _env("EXIT_GEO_ENABLED", True)
    EXIT_GEO_URL: str = _env("EXIT_GEO_URL", "https://ipwho.is/")


settings = Settings()


def github_publish_enabled() -> bool:
    return bool(settings.GITHUB_TOKEN and settings.GITHUB_REPO)


def github_sub_url() -> str | None:
    if not github_publish_enabled():
        return None
    s = settings
    return f"https://raw.githubusercontent.com/{s.GITHUB_REPO}/{s.GITHUB_BRANCH}/{s.GITHUB_SUB_PATH.lstrip('/')}"


_GITHUB_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def validate_settings(s: Settings = settings) -> list[str]:
    problems = []

    def need(ok: bool, message: str) -> None:
        if not ok:
            problems.append(message)

    for name in ("TEST_CONCURRENCY", "FUNCTIONAL_TEST_CHUNK_SIZE", "FUNCTIONAL_TEST_CONCURRENCY",
                 "FUNCTIONAL_TEST_BATCH_SIZE", "FUNCTIONAL_TEST_ATTEMPTS", "FUNCTIONAL_TEST_MIN_PASSES",
                 "FETCH_INTERVAL_MINUTES", "VERIFIED_FILE_LIMIT",
                 "FUNCTIONAL_TEST_DOWNLOAD_CONCURRENCY"):
        need(getattr(s, name) >= 1, f"{name} must be at least 1")
    for name in ("TCP_TIMEOUT_SECONDS", "FUNCTIONAL_TEST_TIMEOUT_SECONDS",
                 "FUNCTIONAL_TEST_STARTUP_SECONDS", "FUNCTIONAL_TEST_DOWNLOAD_TIMEOUT_SECONDS",
                 "REVERIFY_INTERVAL_HOURS"):
        need(getattr(s, name) > 0, f"{name} must be greater than 0")
    for name in ("GEOIP_BATCH_DELAY_SECONDS", "PUBLISH_MIN_INTERVAL_MINUTES",
                 "FUNCTIONAL_TEST_MAX_LATENCY_MS", "FUNCTIONAL_TEST_DOWNLOAD_MIN_BYTES"):
        need(getattr(s, name) >= 0, f"{name} must not be negative")
    need(s.FUNCTIONAL_TEST_MIN_PASSES <= s.FUNCTIONAL_TEST_ATTEMPTS,
         "FUNCTIONAL_TEST_MIN_PASSES cannot exceed FUNCTIONAL_TEST_ATTEMPTS")
    need(100 <= s.FUNCTIONAL_TEST_EXPECTED_STATUS <= 599, "FUNCTIONAL_TEST_EXPECTED_STATUS must be an HTTP status")
    for name in ("GITHUB_RAW_URL", "FUNCTIONAL_TEST_URL", "EXIT_GEO_URL"):
        need(getattr(s, name).startswith(("http://", "https://")), f"{name} must be an http(s) URL")
    for name in ("FUNCTIONAL_TEST_SECOND_URL", "FUNCTIONAL_TEST_DOWNLOAD_URL"):
        value = getattr(s, name)
        need(not value or value.startswith(("http://", "https://")), f"{name} must be an http(s) URL or empty")
    if s.GITHUB_REPO:
        need(bool(_GITHUB_REPO_RE.match(s.GITHUB_REPO)), "GITHUB_REPO must look like owner/name")
    need(bool(s.GITHUB_SUB_PATH.strip("/")), "GITHUB_SUB_PATH must not be empty")
    return problems
