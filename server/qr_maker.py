from __future__ import annotations

import io
from functools import lru_cache


def make_svg(text: str) -> bytes:
    text = str(text or "").strip()
    if not text:
        raise ValueError("QR text порожній")
    if len(text) > 1024:
        raise ValueError("QR text завеликий")
    return _render_svg(text)


@lru_cache(maxsize=64)
def _render_svg(text: str) -> bytes:
    try:
        import qrcode
        import qrcode.image.svg
    except Exception as exc:
        raise RuntimeError("Потрібен пакет python3-qrcode") from exc

    factory = qrcode.image.svg.SvgPathImage
    img = qrcode.make(
        text,
        image_factory=factory,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        border=2,
        box_size=8,
    )
    out = io.BytesIO()
    img.save(out)
    return out.getvalue()
