"""Private-only, unattended YouTube publishing for completed Knowledge Nuggets."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import requests

from .config import (
    YOUTUBE_OAUTH_CLIENT_ID,
    YOUTUBE_OAUTH_CLIENT_SECRET,
    YOUTUBE_OAUTH_REFRESH_TOKEN,
)


TOKEN_URL = "https://oauth2.googleapis.com/token"
RESUMABLE_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"


class YouTubePublishError(RuntimeError):
    pass


def _oauth_client_fields() -> dict[str, str]:
    if not YOUTUBE_OAUTH_CLIENT_ID:
        raise YouTubePublishError("private YouTube publishing is not configured: set KN_YOUTUBE_OAUTH_CLIENT_ID")
    fields = {"client_id": YOUTUBE_OAUTH_CLIENT_ID}
    # Google classifies a desktop-client secret as optional. Retaining it when
    # available also supports the web client used by the production worker.
    if YOUTUBE_OAUTH_CLIENT_SECRET:
        fields["client_secret"] = YOUTUBE_OAUTH_CLIENT_SECRET
    return fields


def _access_token(refresh_token: str | None = None) -> str:
    refresh_token = refresh_token or YOUTUBE_OAUTH_REFRESH_TOKEN
    if not refresh_token:
        raise YouTubePublishError(
            "private YouTube publishing is not configured: set KN_YOUTUBE_OAUTH_CLIENT_ID and KN_YOUTUBE_OAUTH_REFRESH_TOKEN"
        )
    try:
        payload = _oauth_client_fields() | {
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        }
        response = requests.post(
            TOKEN_URL,
            data=payload,
            timeout=(10, 30),
        )
        response.raise_for_status()
        token = str(response.json().get("access_token") or "")
    except (requests.RequestException, ValueError) as exc:
        raise YouTubePublishError(f"could not refresh the YouTube publishing token: {exc}") from exc
    if not token:
        raise YouTubePublishError("YouTube token refresh returned no access token")
    return token


def exchange_authorization_code(code: str, redirect_uri: str) -> str:
    """Exchange the one-time Google callback code for an unattended refresh token."""
    if not code or not redirect_uri:
        raise YouTubePublishError("OAuth authorization code and redirect URI are required")
    try:
        payload = _oauth_client_fields() | {
            "code": code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        response = requests.post(TOKEN_URL, data=payload, timeout=(10, 30))
        response.raise_for_status()
        refresh_token = str(response.json().get("refresh_token") or "")
    except (requests.RequestException, ValueError) as exc:
        raise YouTubePublishError(f"could not exchange the YouTube authorization code: {exc}") from exc
    if not refresh_token:
        raise YouTubePublishError("Google did not return a refresh token; grant consent again")
    return refresh_token


def publish_private_short(
    video_path: Path,
    title: str,
    description: str,
    refresh_token: str | None = None,
) -> dict[str, Any]:
    """Upload an MP4 as a private video and return its immutable video id.

    The privacy field is intentionally hard-coded. This worker has no public or
    unlisted publishing path, so a failed review can never accidentally expose
    a Short.
    """
    if not video_path.is_file():
        raise YouTubePublishError("rendered preview is missing before YouTube upload")
    if not title or not description.startswith(title) or len(title) > 100:
        raise YouTubePublishError("title must be at most 100 characters and start the description exactly")
    token = _access_token(refresh_token)
    metadata = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": "27",
        },
        "status": {
            "privacyStatus": "private",
            "selfDeclaredMadeForKids": False,
        },
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Length": str(video_path.stat().st_size),
        "X-Upload-Content-Type": "video/mp4",
    }
    try:
        session = requests.post(
            RESUMABLE_UPLOAD_URL,
            params={"part": "snippet,status", "uploadType": "resumable"},
            headers=headers,
            json=metadata,
            timeout=(10, 30),
        )
        session.raise_for_status()
        upload_url = str(session.headers.get("Location") or "")
        if not upload_url:
            raise YouTubePublishError("YouTube did not return a resumable upload URL")
        with video_path.open("rb") as video:
            uploaded = requests.put(
                upload_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "video/mp4",
                    "Content-Length": str(video_path.stat().st_size),
                },
                data=video,
                timeout=(20, 600),
            )
        uploaded.raise_for_status()
        video_id = str(uploaded.json().get("id") or "")
    except (requests.RequestException, ValueError) as exc:
        raise YouTubePublishError(f"private YouTube upload failed: {exc}") from exc
    if not video_id:
        raise YouTubePublishError("YouTube accepted the upload but returned no video id")
    return {
        "video_id": video_id,
        "short_url": f"https://youtube.com/shorts/{video_id}",
        "privacy_status": "private",
        "title": title,
    }
