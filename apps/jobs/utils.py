import io
from datetime import timedelta

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from .overlay import THUMBNAIL_MAX_DIM, build_thumbnail_jpeg

# Refresh a bit before the real expiry so a token doesn't die mid-request.
TOKEN_REFRESH_MARGIN = timedelta(seconds=60)


def get_google_access_token(user):
    """Returns a valid Google OAuth access token for the user, refreshing the
    stored one first if it's expired (or close to it).

    Access tokens are short-lived (~1hr); without this, a token fetched once
    at login or page-load time goes stale and every Drive API/Picker call
    starts 401/403ing until the user logs out and back in to force a fresh
    OAuth round-trip.
    """
    try:
        token = user.socialaccount_set.get(provider="google").socialtoken_set.first()
    except Exception:
        return None
    if not token:
        return None

    if token.expires_at and token.expires_at > timezone.now() + TOKEN_REFRESH_MARGIN:
        return token.token

    if not token.token_secret:
        # No refresh_token on file (e.g. it was issued before `access_type=offline`
        # was added, or Google only grants one on first consent) — nothing to
        # refresh with, so fall back to whatever's stored.
        return token.token

    app_config = settings.SOCIALACCOUNT_PROVIDERS.get("google", {}).get("APP", {})
    credentials = Credentials(
        token=token.token,
        refresh_token=token.token_secret,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=app_config.get("client_id"),
        client_secret=app_config.get("secret"),
    )
    try:
        credentials.refresh(Request())
    except RefreshError:
        # Refresh token revoked/invalid — the user will need to sign in again.
        return None

    token.token = credentials.token
    if credentials.expiry:
        token.expires_at = timezone.make_aware(credentials.expiry) if timezone.is_naive(credentials.expiry) else credentials.expiry
    token.save(update_fields=["token", "expires_at"])
    return token.token


def download_drive_image(job_image, user):
    """Download a Google Drive file and attach it to the JobImage instance."""
    access_token = get_google_access_token(user)
    if not access_token or not job_image.drive_file_id:
        return False

    try:
        credentials = Credentials(token=access_token)
        service = build("drive", "v3", credentials=credentials)

        request = service.files().get_media(fileId=job_image.drive_file_id)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

        buffer.seek(0)
        filename = job_image.original_filename or f"{job_image.drive_file_id}.jpg"
        job_image.image.save(filename, ContentFile(buffer.read()), save=True)

        # Same lightweight preview local uploads get — without it the configure
        # page falls back to the full-res original, which is what was loading
        # so slowly for Drive-sourced jobs.
        thumb_bytes = build_thumbnail_jpeg(job_image.image.path, max_dim=THUMBNAIL_MAX_DIM)
        job_image.thumbnail.save(f"{job_image.pk}.jpg", ContentFile(thumb_bytes), save=True)
        return True
    except Exception:
        return False
