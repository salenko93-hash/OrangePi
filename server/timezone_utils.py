from __future__ import annotations

from datetime import datetime, timezone, tzinfo

try:
    from zoneinfo import ZoneInfo
except Exception:  # Extremely defensive for non-standard Python builds.
    ZoneInfo = None  # type: ignore[assignment]


def get_timezone(name: str = "Europe/Kyiv") -> tzinfo:
    """Return requested IANA timezone, falling back without third-party tzdata.

    Linux/Orange Pi normally has /usr/share/zoneinfo, so ZoneInfo is exact.
    Some Windows Python installations do not bundle IANA tzdata; in that case
    use the operating system's configured local timezone. UTC is the final
    safety fallback.
    """
    if ZoneInfo is not None:
        try:
            return ZoneInfo(str(name or "Europe/Kyiv"))
        except Exception:
            pass

    try:
        local = datetime.now().astimezone().tzinfo
        if local is not None:
            return local
    except Exception:
        pass

    return timezone.utc


def local_now(name: str = "Europe/Kyiv") -> datetime:
    return datetime.now(get_timezone(name))
