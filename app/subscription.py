from app import database as db
from app.checker.parser import apply_remark


def flag_emoji(country_code: str | None) -> str:
    if not country_code or len(country_code) != 2:
        return "🏳️"
    return "".join(chr(ord(c.upper()) - ord("A") + 0x1F1E6) for c in country_code)


def build_remark(country_code: str | None, country: str | None = None) -> str:
    name = (country or "").strip() or (country_code.upper() if country_code else "Unknown")
    return f"{flag_emoji(country_code)} {name}"


def remarked_link(raw_link: str, protocol: str, country_code: str | None,
                  country: str | None = None, prefix: str = "") -> str:
    return apply_remark(raw_link, protocol, prefix + build_remark(country_code, country))


async def get_links(limit: int) -> list[str]:
    rows = await db.get_working_configs(limit)
    return [remarked_link(raw, protocol, cc, country) for raw, protocol, cc, country in rows]
