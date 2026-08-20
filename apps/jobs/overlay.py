import base64
import io
import math

from PIL import Image, ImageDraw

from .runpod_client import INFERENCE_SIZE

# Ordered to match class_idx (list position = class_idx), mirroring the segformer
# block of class_mapping.json in the inference container. Small and stable (tied
# to the model's fixed output classes), so it's hardcoded here rather than
# fetched at runtime. Single source of truth for both the overlay palette
# (index-keyed) and the class-proportions chart colors (name-keyed).
CLASS_INFO = [
    ("soil", (55, 52, 25)),
    ("stover", (135, 156, 144)),
    ("pgc", (6, 123, 2)),
    ("weed", (255, 0, 0)),
    ("corn", (120, 124, 243)),
    ("soybean", (255, 242, 0)),
    ("marker", (9, 0, 255)),
    ("quadrat", (255, 171, 171)),
    ("snow", (255, 188, 0)),
    ("namecard", (180, 10, 230)),
    ("person", (39, 47, 72)),
    ("marking_flag", (53, 125, 62)),
]

CLASS_PALETTE = {idx: rgb for idx, (_name, rgb) in enumerate(CLASS_INFO)}
CLASS_COLORS_HEX = {name: "#%02x%02x%02x" % rgb for name, rgb in CLASS_INFO}

ROI_COLOR = (255, 255, 0)
ALPHA = 0.5


def _flat_palette():
    flat = [0] * 768
    for idx, (r, g, b) in CLASS_PALETTE.items():
        flat[idx * 3:idx * 3 + 3] = [r, g, b]
    return flat


def _ordered_roi_points(roi_bboxes, sx, sy):
    """Scale ROI box midpoints to original-image space and order them for a closed polygon."""
    midpoints = [((x1 + x2) / 2 * sx, (y1 + y2) / 2 * sy) for x1, y1, x2, y2 in roi_bboxes]
    cx = sum(p[0] for p in midpoints) / len(midpoints)
    cy = sum(p[1] for p in midpoints) / len(midpoints)
    return sorted(midpoints, key=lambda p: math.atan2(p[1] - cy, p[0] - cx))


def build_overlay_png(job_image, max_dim=None):
    """Render the segmentation class map + ROI polygon over the original image. Returns PNG bytes.

    If max_dim is given, the original is downscaled to fit within it first, so all
    downstream compositing runs on the smaller image (cheap thumbnails vs. full-res).
    """
    result = job_image.result
    original = Image.open(job_image.image.path).convert("RGB")
    orig_w, orig_h = original.size

    if max_dim and max(orig_w, orig_h) > max_dim:
        scale = max_dim / max(orig_w, orig_h)
        orig_w, orig_h = round(orig_w * scale), round(orig_h * scale)
        original = original.resize((orig_w, orig_h), Image.Resampling.LANCZOS)

    class_map_png = base64.b64decode(result["segmentation"]["output_map"])
    class_map = Image.open(io.BytesIO(class_map_png)).convert("L")
    class_map = class_map.resize((orig_w, orig_h), Image.Resampling.NEAREST)

    mask = class_map.point(lambda p: 255 if p != 0 else 0)

    colorized = Image.frombytes("P", class_map.size, class_map.tobytes())
    colorized.putpalette(_flat_palette())
    colorized = colorized.convert("RGB")

    blended = Image.blend(original, colorized, ALPHA)
    overlay = Image.composite(blended, original, mask)

    detection = result.get("detection") or {}
    roi_bboxes = detection.get("roi_bboxes") or []
    if detection.get("region_type") in ("marker", "quadrat") and len(roi_bboxes) == 4:
        sx = orig_w / INFERENCE_SIZE
        sy = orig_h / INFERENCE_SIZE
        points = _ordered_roi_points(roi_bboxes, sx, sy)
        draw = ImageDraw.Draw(overlay)
        draw.polygon(points, outline=ROI_COLOR, width=3)

    buf = io.BytesIO()
    overlay.save(buf, format="PNG")
    return buf.getvalue()
