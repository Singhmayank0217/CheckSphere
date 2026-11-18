"""Decode/validate evidence photos and burn in the CheckSphere GPS watermark (server-side, so agents cannot alter it).

* decode_photo(): fully decodes the upload (JPEG/PNG/WebP/HEIC only) — the client's filename/MIME is never trusted —
  and applies the EXIF orientation so the watermark lands in the visual bottom-right corner.
* render_watermark(): compact, semi-transparent dark box in the bottom-right corner with white text:
      CHECKSPHERE / date | time IST / Latitude / Longitude / Address / Photo
  GPS accuracy, case ids and other technical data are deliberately NOT printed (they stay in MongoDB).
  For selfies and supporting documents a dark strip is added below the photo and the box sits in that strip,
  so it can never cover a face or document text. The photo itself is never stretched or cropped.
"""
import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

try:  # HEIC/HEIF decoding (iPhone/Samsung "high efficiency" photos)
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIF_OK = True
except Exception:  # pragma: no cover
    HEIF_OK = False

FONT_PATH = Path(__file__).parent / "assets" / "fonts" / "PlusJakartaSans.ttf"
ALLOWED_FORMATS = {"JPEG": "jpg", "MPO": "jpg", "PNG": "png", "WEBP": "webp", "HEIF": "heic", "HEIC": "heic"}
MAX_PIXELS = 60_000_000          # refuse decompression bombs
MAX_OUTPUT_SIDE = 4096           # keeps the watermarked JPEG well inside upload limits; proportions preserved
IST = timezone(timedelta(hours=5, minutes=30))
SLOT_TITLES = {"exterior": "Exterior – Front", "exterior_2": "Exterior – Second Angle", "interior": "Interior",
               "selfie": "Selfie", "document": "Supporting Document"}
BAND_SLOTS = {"selfie", "document"}   # watermark goes in an added strip below the photo for these


class InvalidImage(ValueError):
    pass


def decode_photo(data: bytes) -> tuple[Image.Image, str]:
    """Return (RGB image with EXIF orientation applied, safe extension of the original). Raises InvalidImage."""
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        probe = Image.open(io.BytesIO(data))
        fmt = (probe.format or "").upper()
        if fmt not in ALLOWED_FORMATS:
            raise InvalidImage(f"format {fmt or 'unknown'}")
        probe.verify()  # structural check
        img = Image.open(io.BytesIO(data))
        img.load()      # full decode: truncated/corrupt files fail here
    except InvalidImage:
        raise
    except Exception as exc:
        raise InvalidImage(type(exc).__name__) from exc
    img = ImageOps.exif_transpose(img)
    if img.mode != "RGB":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode in ("RGBA", "LA", "P"):
            rgba = img.convert("RGBA")
            bg.paste(rgba, mask=rgba.split()[-1])
            img = bg
        else:
            img = img.convert("RGB")
    return img, ALLOWED_FORMATS[fmt]


def fmt_capture(captured: datetime) -> str:
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=timezone.utc)
    return captured.astimezone(IST).strftime("%d-%b-%Y | %I:%M:%S %p IST")


def watermark_lines(captured: datetime, lat, lon, address: dict, slot: str, slot_label: str | None = None) -> list[str]:
    if lat is not None and lon is not None:
        lat_s, lon_s = f"Latitude: {lat:.6f}", f"Longitude: {lon:.6f}"
    else:
        lat_s, lon_s = "Latitude: Not available", "Longitude: Not available"
    if address.get("text"):
        addr = f"Address{' (approximate)' if address.get('status') == 'approximate' else ''}: {address['text']}"
    else:
        addr = "Address unavailable"
    return ["CHECKSPHERE", fmt_capture(captured), lat_s, lon_s, addr, f"Photo: {SLOT_TITLES.get(slot) or slot_label or slot}"]


def _font(size: int, bold: bool = False):
    f = ImageFont.truetype(str(FONT_PATH), size)
    try:
        f.set_variation_by_name("Bold" if bold else "Medium")
    except Exception:
        pass
    return f


def _wrap(draw, text: str, font, max_w: int, max_lines: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
            while draw.textlength(cur, font=font) > max_w and len(cur) > 1:  # very long token
                cut = len(cur)
                while cut > 1 and draw.textlength(cur[:cut], font=font) > max_w:
                    cut -= 1
                lines.append(cur[:cut])
                cur = cur[cut:]
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and draw.textlength(last + "…", font=font) > max_w:
            last = last[:-1]
        lines[-1] = last.rstrip(" ,") + "…"
    return lines


def render_watermark(img: Image.Image, lines: list[str], slot: str) -> tuple[bytes, dict]:
    """Return (JPEG bytes, layout info)."""
    if max(img.size) > MAX_OUTPUT_SIDE:
        img = img.copy()
        img.thumbnail((MAX_OUTPUT_SIDE, MAX_OUTPUT_SIDE), Image.Resampling.LANCZOS)  # proportional, no distortion
    W, H = img.size
    short = min(W, H)
    title_f = _font(max(15, round(short * 0.027)), bold=True)
    body_f = _font(max(12, round(short * 0.0195)))
    pad = max(8, round(short * 0.018))
    gap = max(2, round(body_f.size * 0.28))
    margin = max(8, round(short * 0.02))
    max_box_w = round(W * (0.40 if W >= H else 0.58))
    measure = ImageDraw.Draw(img)
    text_w = max_box_w - 2 * pad

    rows: list[tuple[str, ImageFont.FreeTypeFont]] = [(lines[0], title_f)]
    for ln in lines[1:]:
        limit = 3 if ln.startswith("Address") else 1
        rows += [(x, body_f) for x in _wrap(measure, ln, body_f, text_w, limit)]
    widths = [measure.textlength(t, font=f) for t, f in rows]
    heights = [f.getbbox("Ag")[3] for _, f in rows]
    box_w = min(max_box_w, round(max(widths) + 2 * pad))
    box_h = round(sum(heights) + gap * (len(rows) - 1) + 2 * pad + gap)  # extra gap under the title

    band = slot in BAND_SLOTS
    if band:  # dedicated strip below the photo: never covers a face or document text
        canvas = Image.new("RGB", (W, H + box_h + 2 * margin), (24, 26, 28))
        canvas.paste(img, (0, 0))
    else:
        canvas = img.copy()
    CW, CH = canvas.size
    x0, y0 = CW - margin - box_w, CH - margin - box_h

    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rounded_rectangle([x0, y0, x0 + box_w, y0 + box_h], radius=max(6, pad // 2), fill=(0, 0, 0, 165))
    od.rectangle([x0, y0 + pad, x0 + max(3, pad // 3), y0 + box_h - pad], fill=(46, 160, 92, 230))  # brand accent
    y = y0 + pad
    for i, ((t, f), h) in enumerate(zip(rows, heights)):
        od.text((x0 + pad, y), t, font=f, fill=(255, 255, 255, 255))
        y += h + gap + (gap if i == 0 else 0)
    out = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=88, optimize=True, progressive=True)
    data = buf.getvalue()
    Image.open(io.BytesIO(data)).load()  # the final file must open cleanly
    return data, {"box": [x0, y0, box_w, box_h], "size": [CW, CH], "photo_size": [W, H], "band": band,
                  "printed_lines": [t for t, _ in rows]}
