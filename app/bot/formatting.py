SAFE_LIMIT = 3900


def fmt_duration(seconds: float) -> str:
    days, rem = divmod(max(0, int(seconds)), 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{max(minutes, 1)}m"


def split_messages(header: str, entries: list[str], footer: str, limit: int = SAFE_LIMIT) -> list[str]:
    budget = limit - len(footer) - 2
    chunks, current = [], header
    for entry in entries:
        if current and len(current) + len(entry) + 2 > budget:
            chunks.append(current)
            current = ""
        current = f"{current}\n\n{entry}" if current else entry
    chunks.append(current)
    chunks[-1] += f"\n\n{footer}"
    return chunks


def fits_alone(entry: str, header: str, footer: str, limit: int = SAFE_LIMIT) -> bool:
    return len(entry) + len(header) + len(footer) + 4 <= limit
