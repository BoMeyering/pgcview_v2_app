import base64
import io
import time

import requests
from django.conf import settings
from PIL import Image

INFERENCE_SIZE = 1024


class RunPodError(Exception):
    pass


def _prepare_image(image_bytes):
    """Resize to the model's fixed input size before sending.

    The container always force-resizes to (MODEL_IMAGE_SIZE, MODEL_IMAGE_SIZE)
    before inference regardless of what we send, so doing it here only shrinks
    the upload payload — it doesn't change what the model sees.
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    img = img.resize((INFERENCE_SIZE, INFERENCE_SIZE), Image.Resampling.BILINEAR)

    # The container decodes with cv2.imdecode(..., cv2.IMREAD_COLOR), which always
    # returns a BGR-ordered array, then normalizes it against ImageNet means quoted
    # in R,G,B order (0.485, 0.456, 0.406) — i.e. it expects the *decoded* array to
    # already be RGB-ordered. A normal JPEG (true colors, no swap) decodes to BGR
    # there, which is wrong. Swapping R/B before encoding here means OpenCV's BGR
    # decode lands back on true RGB order, matching what preprocess() assumes.
    r, g, b = img.split()
    img = Image.merge("RGB", (b, g, r))

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=100)
    return buf.getvalue()


def wait_for_ready(timeout=120, interval=3):
    """Poll /ping until it returns 200 or the timeout elapses. Returns True once ready."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            response = requests.get(
                f"{settings.RUNPOD_BASE_URL}/ping",
                headers={"Authorization": f"Bearer {settings.RUNPOD_API_KEY}"},
                timeout=10,
            )
            if response.status_code == 200:
                return True
        except requests.RequestException:
            pass

        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)


def run_full_pipeline(image_bytes, img_name="", conf=0.85, marker_type="all", timeout=120):
    """Call the RunPod /full_pipeline endpoint and return the parsed JSON response."""
    b64_str = base64.b64encode(_prepare_image(image_bytes)).decode("ascii")
    try:
        response = requests.post(
            f"{settings.RUNPOD_BASE_URL}/full_pipeline",
            params={
                "conf": conf,
                "marker_type": marker_type,
                "logits": False,
                "bboxes": False,
                "output_map": True,
            },
            json={"b64_str": b64_str, "metadata": {"img_name": img_name}},
            headers={"Authorization": f"Bearer {settings.RUNPOD_API_KEY}"},
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        raise RunPodError(str(e)) from e
    return response.json()
