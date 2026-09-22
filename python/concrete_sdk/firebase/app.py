"""Project/region constants and idempotent Firebase Admin initialisation.

Shared by every Concrete Python deployment (forum's Cloud Functions codebases,
langgraph-agent). Deployment-specific values — Cloud Tasks invoker SAs, function
URLs, per-project numbers — stay in the consuming repo.
"""
import os

# Cloud Functions / Cloud Tasks / Firestore triggers (Zurich).
REGION = "europe-west6"
# Vertex AI RAG Engine corpus + imports (Frankfurt — west6 LRO pool is stuck).
RAG_REGION = "europe-west3"

# Browser origins allowed to call Concrete HTTP functions directly.
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "https://planerhub-d731e.web.app",
    "https://planerhub-d731e.firebaseapp.com",
    "https://concrete.ch",
    "https://www.concrete.ch",
    "https://beta-16080.web.app",
    "https://beta-16080.firebaseapp.com",
    "https://concrete-beta-2026.web.app",
    "https://concrete-beta-2026.firebaseapp.com",
]

CORS_METHODS = ["GET", "POST", "OPTIONS"]


def project_id(default: str = "planerhub-d731e") -> str:
    """Resolve the active GCP/Firebase project.

    Cloud Functions sets GCLOUD_PROJECT; langgraph-agent sets FIREBASE_PROJECT_ID;
    generic GCP tooling sets GOOGLE_CLOUD_PROJECT.
    """
    return (
        os.environ.get("GCLOUD_PROJECT")
        or os.environ.get("FIREBASE_PROJECT_ID")
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
        or default
    )


PROJECT_ID = project_id()


def ensure_app():
    """Initialise the default firebase_admin app once, using ADC.

    Safe to call repeatedly and from multiple modules — returns the existing app
    if one is already initialised. Callers needing service-account credentials or
    a secondary app (e.g. langgraph-agent verifying tokens from two projects)
    should keep doing their own `firebase_admin.initialize_app`; this covers the
    common in-GCP case where ADC is already correct.
    """
    import firebase_admin

    if firebase_admin._apps:
        return firebase_admin.get_app()
    return firebase_admin.initialize_app()
