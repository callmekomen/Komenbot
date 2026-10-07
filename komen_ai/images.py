"""
Komen AI - Image helpers for vision.

Screenshots are big (a 4K screen is ~8MP) and every provider charges by image
tokens, so we downscale before sending. 1568px on the long edge is the point
past which most vision models stop gaining accuracy.
"""
import base64
import io
import os

MAX_EDGE = 1568
JPEG_QUALITY = 80

try:
    from PIL import Image
    _HAS_PIL = True
except ImportError:
    _HAS_PIL = False


def encode_image(path: str) -> dict:
    """
    Returns {"media_type": "image/...", "data": "<base64>"} or {"error": ...}.
    Downscales via Pillow when available; falls back to sending raw bytes.
    """
    if not os.path.exists(path):
        return {"error": f"Image not found: {path}"}

    if not _HAS_PIL:
        try:
            with open(path, "rb") as f:
                raw = f.read()
            ext = os.path.splitext(path)[1].lower()
            media = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
            return {"media_type": media, "data": base64.b64encode(raw).decode("ascii")}
        except Exception as e:
            return {"error": f"Could not read image: {e}"}

    try:
        img = Image.open(path)
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")

        w, h = img.size
        if max(w, h) > MAX_EDGE:
            scale = MAX_EDGE / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=JPEG_QUALITY)
        return {
            "media_type": "image/jpeg",
            "data": base64.b64encode(buf.getvalue()).decode("ascii"),
            "original_size": f"{w}x{h}",
            "sent_size": f"{img.size[0]}x{img.size[1]}",
        }
    except Exception as e:
        return {"error": f"Could not process image: {e}"}
