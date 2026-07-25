"""Thin GCS upload wrapper. Auth via Application Default Credentials only."""
from google.cloud import storage


def upload_bytes(bucket_name: str, blob_path: str, data: bytes, content_type: str) -> str:
    """Upload bytes to a bucket and return the gs:// URI."""
    client = storage.Client()
    blob = client.bucket(bucket_name).blob(blob_path)
    blob.upload_from_string(data, content_type=content_type)
    return f"gs://{bucket_name}/{blob_path}"
