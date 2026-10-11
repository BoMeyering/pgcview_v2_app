"""
Management command: build_sample_thumbnails

Pre-renders a thumbnail for every baked-in sample image into
    sample_images/thumbs/<name>.jpg

Generating these on each "Try a Sample Job" click means decoding 18
full-resolution JPEGs per request (~3.5s), long enough that the button looks
broken. The Dockerfile runs this once at build time; populate_sample_images
falls back to generating on the fly for any thumbnail that's missing (e.g. in
a dev checkout that never ran this).
"""

from django.core.management.base import BaseCommand

from apps.jobs.overlay import THUMBNAIL_MAX_DIM, build_thumbnail_jpeg
from apps.jobs.utils import SAMPLE_IMAGES_DIR, SAMPLE_THUMBS_DIR


class Command(BaseCommand):
    help = "Pre-render thumbnails for the baked-in sample images."

    def handle(self, *args, **options):
        SAMPLE_THUMBS_DIR.mkdir(exist_ok=True)
        paths = sorted(SAMPLE_IMAGES_DIR.glob("*.jpg"))
        for path in paths:
            thumb_bytes = build_thumbnail_jpeg(path, max_dim=THUMBNAIL_MAX_DIM)
            (SAMPLE_THUMBS_DIR / path.name).write_bytes(thumb_bytes)
        self.stdout.write(self.style.SUCCESS(f"Built {len(paths)} sample thumbnail(s)."))
