import os
import json

import firebase_admin
from firebase_admin import auth, credentials

from app.core.config import settings


def _initialize_firebase() -> None:
    if firebase_admin._apps:
        return

    options = {"projectId": settings.FIREBASE_PROJECT_ID}
    if settings.FIREBASE_CREDENTIALS_PATH:
        cred_path = os.path.abspath(settings.FIREBASE_CREDENTIALS_PATH)
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred, options)
    elif settings.FIREBASE_CREDENTIALS_JSON:
        cred = credentials.Certificate(json.loads(settings.FIREBASE_CREDENTIALS_JSON))
        firebase_admin.initialize_app(cred, options)
    else:
        raise RuntimeError("Firebase Admin credentials are not configured")


def verify_firebase_id_token(id_token: str) -> dict:
    _initialize_firebase()
    return auth.verify_id_token(id_token)
