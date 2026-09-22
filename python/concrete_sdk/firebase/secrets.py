"""Secret Manager helpers (JSON payloads, one secret per integration)."""
import json

from .app import PROJECT_ID

_client = None


def _get_client():
    global _client
    if _client is None:
        from google.cloud import secretmanager

        _client = secretmanager.SecretManagerServiceClient()
    return _client


def upsert_secret(secret_id: str, payload: dict, *, project_id: str | None = None) -> None:
    """Create or update a secret. Always adds a new version with the full payload."""
    from google.api_core.exceptions import AlreadyExists

    client = _get_client()
    parent = f"projects/{project_id or PROJECT_ID}"
    name = f"{parent}/secrets/{secret_id}"
    data = json.dumps(payload).encode("utf-8")

    try:
        client.create_secret(request={
            "parent": parent,
            "secret_id": secret_id,
            "secret": {"replication": {"automatic": {}}},
        })
    except AlreadyExists:
        pass  # Secret exists — just add a new version below

    client.add_secret_version(request={
        "parent": name,
        "payload": {"data": data},
    })


def get_secret(secret_id: str, *, project_id: str | None = None) -> dict:
    """Read the latest version of a secret and return it as a dict."""
    name = f"projects/{project_id or PROJECT_ID}/secrets/{secret_id}/versions/latest"
    response = _get_client().access_secret_version(request={"name": name})
    return json.loads(response.payload.data.decode("utf-8"))
