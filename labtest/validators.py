from urllib.parse import urlparse

from django.conf import settings
from django.core.exceptions import ValidationError

# Only accept files the frontend uploaded to our Cloudinary account.
# Optional: LABTESTS_ALLOWED_FILE_HOSTS = ["res.cloudinary.com"] in settings.py
ALLOWED_HOSTS = getattr(settings, "LABTESTS_ALLOWED_FILE_HOSTS", ["res.cloudinary.com"])
ALLOWED_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png")


def validate_lab_file_url(value):
    parsed = urlparse(value)
    if parsed.scheme != "https":
        raise ValidationError("File URL must use https.")
    if parsed.hostname not in ALLOWED_HOSTS:
        raise ValidationError("File must be uploaded to our file storage.")
    if not parsed.path.lower().endswith(ALLOWED_EXTENSIONS):
        raise ValidationError("Only PDF, JPG and PNG files are allowed.")