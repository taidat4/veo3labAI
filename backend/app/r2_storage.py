"""
R2/S3 Storage — Lưu video vào Cloudflare R2

Khi video generate xong, Google trả về URL tạm (signed, expire 1 giờ).
Module này download video đó và upload lên R2 để lưu vĩnh viễn.
"""

import logging
import io
from typing import Optional

try:
    import boto3
    from botocore.config import Config as BotoConfig
except ImportError:
    boto3 = None
    BotoConfig = None
import httpx

from app.config import get_settings

logger = logging.getLogger("veo3.r2")
settings = get_settings()


class R2Storage:
    """Cloudflare R2 (S3-compatible) storage"""

    def __init__(self):
        self._client = None

    @property
    def client(self):
        """Lazy-init S3 client"""
        if self._client is None:
            if not settings.R2_ENDPOINT or not settings.R2_ACCESS_KEY:
                logger.warning("⚠️ R2 chưa cấu hình — video sẽ không lưu lâu dài")
                return None

            self._client = boto3.client(
                "s3",
                endpoint_url=settings.R2_ENDPOINT,
                aws_access_key_id=settings.R2_ACCESS_KEY,
                aws_secret_access_key=settings.R2_SECRET_KEY,
                config=BotoConfig(
                    signature_version="s3v4",
                    retries={"max_attempts": 3, "mode": "standard"},
                ),
                region_name="auto",
            )
        return self._client

    @property
    def is_configured(self) -> bool:
        return bool(settings.R2_ENDPOINT and settings.R2_ACCESS_KEY)

    async def upload_from_url(
        self,
        source_url: str,
        r2_key: str,
        content_type: str = "video/mp4",
    ) -> Optional[str]:
        """
        Download video từ URL tạm và upload lên R2.

        Args:
            source_url: URL video tạm từ Google
            r2_key: Key trong R2 (vd: "videos/user_1/job_123.mp4")
            content_type: MIME type

        Returns:
            Public URL hoặc None nếu thất bại
        """
        if not self.client:
            logger.warning("⚠️ R2 chưa cấu hình, skip upload")
            return None

        try:
            logger.info(f"📥 Downloading video từ Google ({source_url[:80]}...)...")

            async with httpx.AsyncClient(timeout=120, follow_redirects=True) as http:
                resp = await http.get(source_url)
                if resp.status_code != 200:
                    logger.error(f"❌ Download failed: HTTP {resp.status_code}")
                    return None

                video_data = resp.content
                logger.info(f"📥 Downloaded {len(video_data) / 1024 / 1024:.1f}MB")

            # Upload lên R2
            logger.info(f"📤 Uploading to R2: {r2_key}")
            self.client.put_object(
                Bucket=settings.R2_BUCKET,
                Key=r2_key,
                Body=video_data,
                ContentType=content_type,
            )

            # Build public URL
            public_url = f"{settings.R2_PUBLIC_URL}/{r2_key}" if settings.R2_PUBLIC_URL else None
            logger.info(f"✅ Upload done: {public_url or r2_key}")
            return public_url

        except Exception as e:
            logger.error(f"❌ Upload failed: {e}")
            return None

    async def upload_bytes(
        self,
        data: bytes,
        r2_key: str,
        content_type: str = "video/mp4",
    ) -> Optional[str]:
        """Upload raw bytes lên R2"""
        if not self.client:
            return None

        try:
            self.client.put_object(
                Bucket=settings.R2_BUCKET,
                Key=r2_key,
                Body=data,
                ContentType=content_type,
            )
            return f"{settings.R2_PUBLIC_URL}/{r2_key}" if settings.R2_PUBLIC_URL else r2_key
        except Exception as e:
            logger.error(f"❌ Upload bytes failed: {e}")
            return None

    def get_presigned_url(self, r2_key: str, expires_in: int = 3600) -> Optional[str]:
        """Lấy presigned URL cho video (dùng khi không có public domain)"""
        if not self.client:
            return None

        try:
            url = self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": settings.R2_BUCKET, "Key": r2_key},
                ExpiresIn=expires_in,
            )
            return url
        except Exception as e:
            logger.error(f"❌ Presigned URL failed: {e}")
            return None

    async def delete(self, r2_key: str):
        """Xóa video từ R2"""
        if not self.client:
            return

        try:
            self.client.delete_object(Bucket=settings.R2_BUCKET, Key=r2_key)
            logger.info(f"🗑️ Deleted: {r2_key}")
        except Exception as e:
            logger.error(f"❌ Delete failed: {e}")


# Singleton
r2_storage = R2Storage()
