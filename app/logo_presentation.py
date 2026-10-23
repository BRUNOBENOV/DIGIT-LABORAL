"""Render stored company logos using each client's saved presentation preferences."""

from __future__ import annotations

import io

from PIL import Image, ImageChops, ImageOps


_CANVAS = (1100, 360)
_BASE_BOX = (980, 280)
_BACKGROUNDS = {
    "white": (255, 255, 255, 255),
    "transparent": (255, 255, 255, 0),
    "soft": (232, 239, 252, 255),
    "navy": (11, 45, 120, 255),
}


def prepare_company_logo(
    logo_bytes: bytes | None,
    *,
    fit: str = "contain",
    scale: int = 100,
    alignment: str = "center",
    background: str = "white",
) -> bytes | None:
    """Return a presentation-ready PNG without mutating the stored source image."""
    if not logo_bytes:
        return None

    fit = fit if fit in {"contain", "cover"} else "contain"
    alignment = alignment if alignment in {"left", "center", "right"} else "center"
    background = background if background in _BACKGROUNDS else "white"
    try:
        scale = max(60, min(140, int(scale or 100)))
        with Image.open(io.BytesIO(logo_bytes)) as opened:
            image = ImageOps.exif_transpose(opened).convert("RGBA")
        alpha_bounds = image.getchannel("A").getbbox()
        if alpha_bounds:
            image = image.crop(alpha_bounds)

        # Older JPEG-based uploads can leave white padding inside the normalized canvas.
        white = Image.new("RGBA", image.size, (255, 255, 255, 255))
        content_bounds = ImageChops.difference(image, white).getbbox()
        if content_bounds:
            image = image.crop(content_bounds)

        target = (
            max(1, round(_BASE_BOX[0] * scale / 100)),
            max(1, round(_BASE_BOX[1] * scale / 100)),
        )
        if fit == "cover":
            resized = ImageOps.fit(image, target, method=Image.Resampling.LANCZOS)
        else:
            resized = ImageOps.contain(image, target, method=Image.Resampling.LANCZOS)

        canvas = Image.new("RGBA", _CANVAS, _BACKGROUNDS[background])
        x = 0 if alignment == "left" else _CANVAS[0] - resized.width if alignment == "right" else (_CANVAS[0] - resized.width) // 2
        y = (_CANVAS[1] - resized.height) // 2
        canvas.paste(resized, (x, y), resized)

        output = io.BytesIO()
        canvas.save(output, format="PNG", optimize=True)
        return output.getvalue()
    except (OSError, ValueError, TypeError):
        # A previously validated source should not make document exports fail.
        return logo_bytes
