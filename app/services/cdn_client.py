import json
import logging
from typing import Any, Dict, List, Optional
import boto3
import httpx
from botocore.exceptions import ClientError
from app.config import get_settings

logger = logging.getLogger("zerodaily.cdn")
logger.setLevel(logging.INFO)

CLOUDFLARE_PURGE_URL_TEMPLATE = "https://api.cloudflare.com/client/v4/zones/{zone_id}/purge_cache"
MAX_PURGE_URLS_PER_REQUEST = 30  # Cloudflare single-file purge limit per request


class CDNClient:
    """
    Client for managing Cloudflare CDN cache invalidation and edge pre-warming.
    Supports credentials from args, environment variables, or AWS Secrets Manager.
    """

    def __init__(
        self,
        zone_id: Optional[str] = None,
        api_token: Optional[str] = None,
        api_domain: Optional[str] = None,
        media_domain: Optional[str] = None,
    ):
        settings = get_settings()
        self.zone_id = zone_id or settings.CLOUDFLARE_ZONE_ID
        self.api_token = api_token or settings.CLOUDFLARE_API_TOKEN
        self.api_domain = (api_domain or settings.API_DOMAIN).rstrip("/")
        self.media_domain = (media_domain or settings.MEDIA_DOMAIN).rstrip("/")

        # If not provided via env, check consolidated secret in AWS Secrets Manager
        if not self.zone_id or not self.api_token:
            self._load_credentials_from_secrets_manager()

    def _load_credentials_from_secrets_manager(self) -> None:
        """Loads Cloudflare credentials from the consolidated secret in AWS Secrets Manager."""
        settings = get_settings()
        secret_name = settings.FIREBASE_SECRET_NAME or "zerodaily/firebase-key"
        try:
            client = boto3.client("secretsmanager", region_name=settings.AWS_REGION)
            response = client.get_secret_value(SecretId=secret_name)
            secret_string = response.get("SecretString")
            if secret_string:
                data = json.loads(secret_string)
                if not self.zone_id and "cloudflare_zone_id" in data:
                    self.zone_id = data["cloudflare_zone_id"]
                if not self.api_token and "cloudflare_api_token" in data:
                    self.api_token = data["cloudflare_api_token"]
        except Exception as e:
            logger.debug(f"Could not load Cloudflare credentials from Secrets Manager: {e}")

    def purge_cache(self, urls: List[str]) -> bool:
        """
        Purges specific URLs from the Cloudflare edge cache using the single-file purge API.
        
        API Reference: POST https://api.cloudflare.com/client/v4/zones/:zone_id/purge_cache
        Body: {"files": ["https://..."]}
        """
        if not urls:
            logger.info("No URLs provided for CDN cache purge.")
            return True

        if not self.zone_id or not self.api_token:
            logger.warning(
                "Cloudflare credentials (CLOUDFLARE_ZONE_ID or CLOUDFLARE_API_TOKEN) not configured. "
                "Skipping edge cache purge."
            )
            return False

        # Clean and deduplicate URLs
        clean_urls = list(dict.fromkeys(u.strip() for u in urls if u and u.strip()))
        if not clean_urls:
            return True

        url = CLOUDFLARE_PURGE_URL_TEMPLATE.format(zone_id=self.zone_id)
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }

        all_success = True

        # Cloudflare allows up to 30 URLs per single purge request
        for i in range(0, len(clean_urls), MAX_PURGE_URLS_PER_REQUEST):
            batch = clean_urls[i : i + MAX_PURGE_URLS_PER_REQUEST]
            payload = {"files": batch}

            try:
                with httpx.Client(timeout=10.0) as client:
                    response = client.post(url, headers=headers, json=payload)
                    res_json = response.json() if response.content else {}

                    if response.is_success and res_json.get("success"):
                        logger.info(
                            f"Successfully purged {len(batch)} URLs from Cloudflare CDN edge. "
                            f"Purge ID: {res_json.get('result', {}).get('id', 'N/A')}"
                        )
                    else:
                        errors = res_json.get("errors", [])
                        logger.error(
                            f"Failed to purge Cloudflare cache (Status: {response.status_code}): {errors or response.text}"
                        )
                        all_success = False
            except Exception as e:
                logger.error(f"Network error while calling Cloudflare purge API: {e}")
                all_success = False

        return all_success

    def purge_feed_cache(self, categories: Optional[List[str]] = None) -> bool:
        """
        Convenience method to purge the global feed and category feeds.
        Constructs canonical URLs and sends them to purge_cache.
        """
        urls_to_purge = [f"{self.api_domain}/api/v1/feed"]

        if categories:
            for cat in categories:
                clean_cat = cat.strip().lower()
                if clean_cat and clean_cat != "all":
                    urls_to_purge.append(f"{self.api_domain}/api/v1/feed/{clean_cat}")

        logger.info(f"Triggering CDN feed purge for {len(urls_to_purge)} endpoint(s)...")
        return self.purge_cache(urls_to_purge)

    def warm_cache(self, urls: List[str]) -> int:
        """
        Pings URLs using HTTP GET to trigger Cloudflare edge caching.
        Returns the number of successfully warmed URLs.
        """
        if not urls:
            return 0

        clean_urls = list(dict.fromkeys(u.strip() for u in urls if u and u.strip()))
        warmed_count = 0

        with httpx.Client(timeout=6.0, follow_redirects=True) as client:
            for url in clean_urls:
                try:
                    res = client.get(url, headers={"User-Agent": "ZeroDaily-CDNWarming/1.0"})
                    if res.is_success:
                        warmed_count += 1
                        cf_cache = res.headers.get("cf-cache-status", "UNKNOWN")
                        logger.info(f"Warmed CDN cache for '{url}' [CF-Cache: {cf_cache}, Status: {res.status_code}]")
                    else:
                        logger.warning(f"CDN warming ping returned status {res.status_code} for '{url}'")
                except Exception as e:
                    logger.warning(f"Failed to ping URL for CDN warming '{url}': {e}")

        return warmed_count

    def purge_and_warm(
        self,
        categories: Optional[List[str]] = None,
        image_urls: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Executes complete CDN refresh:
        1. Purges the global feed and category feed endpoints on Cloudflare.
        2. Proactively warms the feeds and newly inserted hero images so users experience 10ms cache hits.
        """
        purge_success = self.purge_feed_cache(categories=categories)

        urls_to_warm = [f"{self.api_domain}/api/v1/feed"]
        if categories:
            for cat in categories:
                clean_cat = cat.strip().lower()
                if clean_cat and clean_cat != "all":
                    urls_to_warm.append(f"{self.api_domain}/api/v1/feed/{clean_cat}")

        if image_urls:
            clean_images = [img for img in image_urls if img and img.startswith("http")]
            urls_to_warm.extend(clean_images[:20])

        warmed_count = self.warm_cache(urls_to_warm)

        summary = {
            "purged": purge_success,
            "warmed_urls_count": warmed_count,
            "total_urls": len(urls_to_warm),
        }
        logger.info(f"CDN purge & warm cycle complete: {summary}")
        return summary
