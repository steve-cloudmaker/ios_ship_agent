"""
App Store Connect API client.

This module is GATED — it only activates when AUTO_SUBMIT=true in .env.
All methods are no-ops when disabled, so the pipeline always runs safely.

To enable:
    AUTO_SUBMIT=true
    APP_STORE_CONNECT_KEY_ID=<your_key_id>
    APP_STORE_CONNECT_ISSUER_ID=<your_issuer_id>
    APP_STORE_CONNECT_KEY_PATH=/path/to/AuthKey_XXXXXX.p8

References:
    https://developer.apple.com/documentation/appstoreconnectapi
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _require_jwt() -> str:
    """
    Generate a JWT for App Store Connect API authentication.

    Returns:
        JWT string

    Raises:
        ImportError: If PyJWT is not installed
        FileNotFoundError: If key file doesn't exist
        RuntimeError: If env vars are missing
    """
    try:
        import jwt  # PyJWT
    except ImportError as exc:
        raise ImportError(
            "PyJWT is required for App Store Connect submission. "
            "Install with: pip install PyJWT cryptography"
        ) from exc

    from ios_ship_agent.core.config import settings

    if not settings.APP_STORE_CONNECT_KEY_ID:
        raise RuntimeError("APP_STORE_CONNECT_KEY_ID is not set")
    if not settings.APP_STORE_CONNECT_ISSUER_ID:
        raise RuntimeError("APP_STORE_CONNECT_ISSUER_ID is not set")

    key_path = Path(settings.APP_STORE_CONNECT_KEY_PATH)
    if not key_path.exists():
        raise FileNotFoundError(f"App Store Connect key not found: {key_path}")

    private_key = key_path.read_text()

    now = int(time.time())
    payload = {
        "iss": settings.APP_STORE_CONNECT_ISSUER_ID,
        "iat": now,
        "exp": now + 1200,  # 20 minutes
        "aud": "appstoreconnect-v1",
    }
    headers = {"alg": "ES256", "kid": settings.APP_STORE_CONNECT_KEY_ID}

    return jwt.encode(payload, private_key, algorithm="ES256", headers=headers)


class AppStoreConnectClient:
    """
    Thin wrapper around the App Store Connect REST API.

    All methods check AUTO_SUBMIT before doing anything real.
    When disabled, every method returns a stub dict and logs a warning.
    """

    BASE_URL = "https://api.appstoreconnect.apple.com/v1"

    def __init__(self) -> None:
        from ios_ship_agent.core.config import settings

        self.enabled = settings.AUTO_SUBMIT
        if not self.enabled:
            logger.info(
                "AppStoreConnectClient: AUTO_SUBMIT=false — "
                "all submission calls are no-ops. Set AUTO_SUBMIT=true to enable."
            )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {_require_jwt()}",
            "Content-Type": "application/json",
        }

    def _noop(self, method: str) -> dict[str, Any]:
        logger.warning(f"AppStoreConnectClient.{method}: skipped (AUTO_SUBMIT=false)")
        return {"status": "skipped", "reason": "AUTO_SUBMIT=false"}

    # ------------------------------------------------------------------
    # App creation / lookup
    # ------------------------------------------------------------------

    def list_apps(self) -> dict[str, Any]:
        """List all apps in App Store Connect."""
        if not self.enabled:
            return self._noop("list_apps")

        import requests  # type: ignore[import]

        resp = requests.get(f"{self.BASE_URL}/apps", headers=self._headers(), timeout=30)
        resp.raise_for_status()
        return resp.json()

    def create_app(
        self,
        bundle_id: str,
        name: str,
        primary_locale: str = "en-US",
        sku: str = "",
    ) -> dict[str, Any]:
        """
        Create a new app in App Store Connect.

        NOTE: The bundle ID must already be registered in the Developer portal.
        """
        if not self.enabled:
            return self._noop("create_app")

        import requests  # type: ignore[import]

        payload = {
            "data": {
                "type": "apps",
                "attributes": {
                    "bundleId": bundle_id,
                    "name": name,
                    "primaryLocale": primary_locale,
                    "sku": sku or bundle_id.replace(".", "-"),
                },
            }
        }
        resp = requests.post(
            f"{self.BASE_URL}/apps",
            headers=self._headers(),
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Version & metadata
    # ------------------------------------------------------------------

    def create_app_store_version(
        self,
        app_id: str,
        version_string: str = "1.0.0",
        platform: str = "IOS",
    ) -> dict[str, Any]:
        """Create a new App Store version."""
        if not self.enabled:
            return self._noop("create_app_store_version")

        import requests  # type: ignore[import]

        payload = {
            "data": {
                "type": "appStoreVersions",
                "attributes": {
                    "versionString": version_string,
                    "platform": platform,
                },
                "relationships": {
                    "app": {"data": {"type": "apps", "id": app_id}}
                },
            }
        }
        resp = requests.post(
            f"{self.BASE_URL}/appStoreVersions",
            headers=self._headers(),
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def update_app_store_version_localization(
        self,
        localization_id: str,
        name: str,
        subtitle: str,
        description: str,
        keywords: str,
        promotional_text: str = "",
        support_url: str = "",
        marketing_url: str = "",
    ) -> dict[str, Any]:
        """Push metadata to a version localization."""
        if not self.enabled:
            return self._noop("update_app_store_version_localization")

        import requests  # type: ignore[import]

        attrs: dict[str, str] = {
            "name": name,
            "subtitle": subtitle,
            "description": description,
            "keywords": keywords,
        }
        if promotional_text:
            attrs["promotionalText"] = promotional_text
        if support_url:
            attrs["supportUrl"] = support_url
        if marketing_url:
            attrs["marketingUrl"] = marketing_url

        payload = {
            "data": {
                "type": "appStoreVersionLocalizations",
                "id": localization_id,
                "attributes": attrs,
            }
        }
        resp = requests.patch(
            f"{self.BASE_URL}/appStoreVersionLocalizations/{localization_id}",
            headers=self._headers(),
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Screenshot upload
    # ------------------------------------------------------------------

    def upload_screenshot(
        self,
        version_localization_id: str,
        screenshot_path: Path,
        display_type: str = "APP_IPHONE_67",
    ) -> dict[str, Any]:
        """
        Upload a screenshot to App Store Connect.

        Args:
            version_localization_id: From the version localization
            screenshot_path: Path to the PNG file
            display_type: App Store screenshot type
                          (APP_IPHONE_67, APP_IPHONE_65, etc.)
        """
        if not self.enabled:
            return self._noop("upload_screenshot")

        import requests  # type: ignore[import]

        data = screenshot_path.read_bytes()
        file_size = len(data)
        file_name = screenshot_path.name

        # Step 1: Reserve upload
        reserve_payload = {
            "data": {
                "type": "appScreenshots",
                "attributes": {
                    "fileSize": file_size,
                    "fileName": file_name,
                },
                "relationships": {
                    "appStoreVersionLocalization": {
                        "data": {
                            "type": "appStoreVersionLocalizations",
                            "id": version_localization_id,
                        }
                    }
                },
            }
        }
        reserve_resp = requests.post(
            f"{self.BASE_URL}/appScreenshots",
            headers=self._headers(),
            json=reserve_payload,
            timeout=30,
        )
        reserve_resp.raise_for_status()
        reservation = reserve_resp.json()

        # Step 2: Upload to the provided URL
        upload_ops = reservation["data"]["attributes"].get("uploadOperations", [])
        for op in upload_ops:
            upload_headers = {h["name"]: h["value"] for h in op.get("requestHeaders", [])}
            upload_resp = requests.put(
                op["url"],
                headers=upload_headers,
                data=data[op["offset"] : op["offset"] + op["length"]],
                timeout=120,
            )
            upload_resp.raise_for_status()

        # Step 3: Commit
        screenshot_id = reservation["data"]["id"]
        commit_payload = {
            "data": {
                "type": "appScreenshots",
                "id": screenshot_id,
                "attributes": {"uploaded": True},
            }
        }
        commit_resp = requests.patch(
            f"{self.BASE_URL}/appScreenshots/{screenshot_id}",
            headers=self._headers(),
            json=commit_payload,
            timeout=30,
        )
        commit_resp.raise_for_status()
        return commit_resp.json()

    # ------------------------------------------------------------------
    # Submit for review
    # ------------------------------------------------------------------

    def submit_for_review(self, version_id: str) -> dict[str, Any]:
        """Submit a version for App Review."""
        if not self.enabled:
            return self._noop("submit_for_review")

        import requests  # type: ignore[import]

        payload = {
            "data": {
                "type": "appStoreVersionSubmissions",
                "relationships": {
                    "appStoreVersion": {
                        "data": {"type": "appStoreVersions", "id": version_id}
                    }
                },
            }
        }
        resp = requests.post(
            f"{self.BASE_URL}/appStoreVersionSubmissions",
            headers=self._headers(),
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()
