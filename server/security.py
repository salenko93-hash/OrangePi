"""Centralized access-key verification, independent of HTTP transport."""

from __future__ import annotations
import hmac


def safe_match(supplied: str, expected: str) -> bool:
    return (
        bool(expected)
        and bool(supplied)
        and hmac.compare_digest(str(supplied).encode(), str(expected).encode())
    )


def resolve_role(config: dict, admin_header: str = "", role_header: str = "") -> str:
    if safe_match(admin_header, config.get("admin_key", "")) or safe_match(
        role_header, config.get("admin_key", "")
    ):
        return "admin"
    if safe_match(role_header, config.get("dispatcher_key", "")):
        return "dispatcher"
    if safe_match(role_header, config.get("teacher_key", "")):
        return "teacher"
    return ""


def allowed(role: str, *roles: str) -> bool:
    return role == "admin" or role in roles
