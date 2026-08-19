import base64
import time

import requests
from django.conf import settings


class RunPodError(Exception):
    pass


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
    b64_str = base64.b64encode(image_bytes).decode("ascii")
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
