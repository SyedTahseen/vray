import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
    ADMIN_IDS: list = field(default_factory=lambda: [
        int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()
    ])

    GITHUB_RAW_URL: str = os.getenv(
        "GITHUB_RAW_URL",
        "https://raw.githubusercontent.com/example/example-repo/main/V2Ray-Config.txt",
    )

    DB_PATH: str = os.getenv("DB_PATH", "v2ray_bot.sqlite3")

    FETCH_INTERVAL_MINUTES: int = int(os.getenv("FETCH_INTERVAL_MINUTES", "10"))
    TCP_TIMEOUT_SECONDS: float = float(os.getenv("TCP_TIMEOUT_SECONDS", "6"))
    TEST_CONCURRENCY: int = int(os.getenv("TEST_CONCURRENCY", "100"))

    REVERIFY_INTERVAL_HOURS: float = float(os.getenv("REVERIFY_INTERVAL_HOURS", "12"))

    GEOIP_BATCH_DELAY_SECONDS: float = float(os.getenv("GEOIP_BATCH_DELAY_SECONDS", "4.2"))

    FUNCTIONAL_TEST_ENABLED: bool = os.getenv("FUNCTIONAL_TEST_ENABLED", "false").lower() == "true"
    XRAY_BIN_PATH: str = os.getenv("XRAY_BIN_PATH", "/usr/local/bin/xray")
    FUNCTIONAL_TEST_URL: str = os.getenv("FUNCTIONAL_TEST_URL", "https://www.gstatic.com/generate_204")
    FUNCTIONAL_TEST_TIMEOUT_SECONDS: float = float(os.getenv("FUNCTIONAL_TEST_TIMEOUT_SECONDS", "10"))
    FUNCTIONAL_TEST_STARTUP_SECONDS: float = float(os.getenv("FUNCTIONAL_TEST_STARTUP_SECONDS", "5"))
    FUNCTIONAL_TEST_CHUNK_SIZE: int = int(os.getenv("FUNCTIONAL_TEST_CHUNK_SIZE", "100"))
    FUNCTIONAL_TEST_CONCURRENCY: int = int(os.getenv("FUNCTIONAL_TEST_CONCURRENCY", "40"))
    FUNCTIONAL_TEST_BATCH_SIZE: int = int(os.getenv("FUNCTIONAL_TEST_BATCH_SIZE", "300"))


    VERIFIED_FILE_LIMIT: int = int(os.getenv("VERIFIED_FILE_LIMIT", "1000"))


settings = Settings()
