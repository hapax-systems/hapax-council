"""Platform dispatch: YouTube Shorts, Instagram Reels, TikTok upload."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)

CITABLE_NEXUS_URL = "https://hapax.github.io"
RAIL_PAGES = {
    "github_sponsors": "https://github.com/sponsors/ryanklee",
    "open_collective": "https://opencollective.com/hapax",
}
NON_ENGAGEMENT_CLAUSE = (
    "This clip was auto-generated from the 24/7 Hapax ambient broadcast. "
    "No engagement is solicited. V5 attribution: hapax.github.io | CC-BY-4.0"
)


class Platform(StrEnum):
    YOUTUBE = "youtube"
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"


@dataclass(frozen=True)
class UploadResult:
    platform: Platform
    success: bool
    video_id: str | None = None
    url: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class ClipMetadata:
    title: str
    description: str
    decoder_channel: str
    tags: list[str]
    clip_id: str


class PlatformUploader(Protocol):
    def upload(self, clip_path: Path, metadata: ClipMetadata) -> UploadResult: ...

    def is_configured(self) -> bool: ...


def build_description(metadata: ClipMetadata) -> str:
    parts = [
        metadata.description,
        "",
        NON_ENGAGEMENT_CLAUSE,
        "",
        f"Channel: {metadata.decoder_channel}",
        f"Canonical: {CITABLE_NEXUS_URL}",
    ]
    for name, url in RAIL_PAGES.items():
        label = name.replace("_", " ").title()
        parts.append(f"{label}: {url}")
    return "\n".join(parts)


class YouTubeUploader:
    def __init__(self) -> None:
        self._credentials_path = os.environ.get("HAPAX_YOUTUBE_CREDENTIALS")

    def is_configured(self) -> bool:
        if self._credentials_path is None:
            return False
        return Path(self._credentials_path).is_file()

    def upload(self, clip_path: Path, metadata: ClipMetadata) -> UploadResult:
        if not self.is_configured():
            return UploadResult(
                platform=Platform.YOUTUBE, success=False, error="credentials_not_configured"
            )
        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload

            creds = Credentials.from_authorized_user_file(self._credentials_path)
            youtube = build("youtube", "v3", credentials=creds)
            body = {
                "snippet": {
                    "title": metadata.title[:100],
                    "description": build_description(metadata)[:5000],
                    "tags": metadata.tags[:30],
                    "categoryId": "28",
                },
                "status": {
                    "privacyStatus": "public",
                    "selfDeclaredMadeForKids": False,
                    "madeForKids": False,
                },
            }
            media = MediaFileUpload(str(clip_path), mimetype="video/mp4", resumable=True)
            request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
            response = request.execute()
            video_id = response.get("id", "")
            return UploadResult(
                platform=Platform.YOUTUBE,
                success=True,
                video_id=video_id,
                url=f"https://youtube.com/shorts/{video_id}",
            )
        except Exception as exc:
            log.warning("YouTube upload failed: %s", exc)
            return UploadResult(platform=Platform.YOUTUBE, success=False, error=str(exc)[:200])


class InstagramUploader:
    def __init__(self) -> None:
        self._token = os.environ.get("HAPAX_INSTAGRAM_ACCESS_TOKEN")
        self._user_id = os.environ.get("HAPAX_INSTAGRAM_USER_ID")

    def is_configured(self) -> bool:
        return bool(self._token and self._user_id)

    def upload(self, clip_path: Path, metadata: ClipMetadata) -> UploadResult:
        if not self.is_configured():
            return UploadResult(
                platform=Platform.INSTAGRAM,
                success=False,
                error="credentials_not_configured",
            )
        log.info("Instagram Reels upload stub")
        return UploadResult(
            platform=Platform.INSTAGRAM,
            success=False,
            error="upload_not_yet_implemented",
        )


class TikTokUploader:
    def __init__(self) -> None:
        self._token = os.environ.get("HAPAX_TIKTOK_ACCESS_TOKEN")

    def is_configured(self) -> bool:
        return bool(self._token)

    def upload(self, clip_path: Path, metadata: ClipMetadata) -> UploadResult:
        if not self.is_configured():
            return UploadResult(
                platform=Platform.TIKTOK,
                success=False,
                error="credentials_not_configured",
            )
        log.info("TikTok upload stub")
        return UploadResult(
            platform=Platform.TIKTOK,
            success=False,
            error="upload_not_yet_implemented",
        )


def get_uploaders() -> dict[Platform, PlatformUploader]:
    return {
        Platform.YOUTUBE: YouTubeUploader(),
        Platform.INSTAGRAM: InstagramUploader(),
        Platform.TIKTOK: TikTokUploader(),
    }


def dispatch_clip(
    clip_path: Path,
    metadata: ClipMetadata,
    *,
    platforms: list[Platform] | None = None,
) -> list[UploadResult]:
    uploaders = get_uploaders()
    targets = platforms or list(Platform)
    results: list[UploadResult] = []

    for platform in targets:
        uploader = uploaders.get(platform)
        if uploader is None:
            continue
        if not uploader.is_configured():
            log.info("Skipping %s", platform.value)
            results.append(UploadResult(platform=platform, success=False, error="not_configured"))
            continue
        result = uploader.upload(clip_path, metadata)
        results.append(result)
        if result.success:
            log.info("Uploaded to %s: %s", platform.value, result.url)
        else:
            log.warning("Upload to %s failed: %s", platform.value, result.error)

    return results
