import io
from django.core.files.base import ContentFile
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2.credentials import Credentials


def get_google_access_token(user):
    try:
        token = user.socialaccount_set.get(provider="google").socialtoken_set.first()
        return token.token if token else None
    except Exception:
        return None


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
        return True
    except Exception:
        return False
