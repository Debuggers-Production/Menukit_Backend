"""Image upload service with MinIO support."""

import uuid
import logging
from io import BytesIO
from typing import Tuple

from PIL import Image
from fastapi import UploadFile
from minio import Minio
from minio.error import S3Error

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

MAX_WIDTH = 1200
THUMBNAIL_WIDTH = 300
JPEG_QUALITY = 80


class UploadService:
    def __init__(self):
        self.minio_endpoint = settings.MINIO_ENDPOINT.replace("https://", "").replace("http://", "")
        self.bucket_name = settings.MINIO_BUCKET_NAME
        self.secure = getattr(settings, "MINIO_SECURE", True)
        self.minio_available = False

        try:
            self.minio_client = Minio(
                self.minio_endpoint,
                access_key=settings.MINIO_ACCESS_KEY,
                secret_key=settings.MINIO_SECRET_KEY,
                secure=self.secure
            )
            self._ensure_bucket_exists()
            self.minio_available = True
        except Exception as e:
            logger.warning(f"MinIO unavailable or invalid credentials ({e}). Falling back to local disk storage.")

    def _ensure_bucket_exists(self):
        try:
            if not self.minio_client.bucket_exists(self.bucket_name):
                self.minio_client.make_bucket(self.bucket_name)

            import json
            policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"AWS": ["*"]},
                        "Action": ["s3:GetObject"],
                        "Resource": [f"arn:aws:s3:::{self.bucket_name}/*"]
                    }
                ]
            }
            try:
                self.minio_client.set_bucket_policy(self.bucket_name, json.dumps(policy))
            except Exception as pe:
                logger.warning(f"Could not set bucket policy: {pe}")

            logger.info(
                f"MinIO bucket '{self.bucket_name}' ready with public read policy"
            )

        except Exception as e:
            logger.warning(f"Failed to verify/create MinIO bucket: {e}")
            raise

    def _upload_local(
        self,
        main_bytes: bytes,
        main_path: str,
    ) -> dict:
        import os
        from pathlib import Path

        base_dir = Path(settings.UPLOAD_DIR)
        main_file = base_dir / main_path
        main_file.parent.mkdir(parents=True, exist_ok=True)

        with open(main_file, "wb") as f:
            f.write(main_bytes)

        image_url = f"http://localhost:8000/uploads/{main_path}"
        logger.info(f"Saved locally: {main_file}")

        return {
            "image_url": image_url,
            "thumbnail_url": image_url,
            "filename": main_path,
            "thumbnail_filename": main_path,
        }

    def _process_image(self, image_data: bytes) -> bytes:
        img = Image.open(BytesIO(image_data))

        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        if img.width > MAX_WIDTH:
            ratio = MAX_WIDTH / img.width
            new_height = int(img.height * ratio)

            img = img.resize(
                (MAX_WIDTH, new_height),
                Image.LANCZOS
            )

        main_buffer = BytesIO()

        img.save(
            main_buffer,
            format="JPEG",
            quality=JPEG_QUALITY,
            optimize=True
        )

        return main_buffer.getvalue()

    async def upload_image(
        self,
        file: UploadFile,
        folder: str = "general"
    ) -> dict:

        contents = await file.read()

        max_bytes = settings.MAX_IMAGE_SIZE_MB * 1024 * 1024

        if len(contents) > max_bytes:
            raise ValueError(
                f"Image size exceeds {settings.MAX_IMAGE_SIZE_MB}MB limit"
            )

        main_bytes = self._process_image(contents)
        file_id = str(uuid.uuid4())
        main_filename = f"{folder}/{file_id}.jpg"

        return await self._upload_minio(
            main_bytes=main_bytes,
            main_path=main_filename,
        )

    async def _upload_minio(
        self,
        main_bytes: bytes,
        main_path: str,
    ) -> dict:
        if not getattr(self, "minio_available", False):
            return self._upload_local(
                main_bytes=main_bytes,
                main_path=main_path,
            )

        try:
            self.minio_client.put_object(
                bucket_name=self.bucket_name,
                object_name=main_path,
                data=BytesIO(main_bytes),
                length=len(main_bytes),
                content_type="image/jpeg",
            )

            protocol = "https" if getattr(self, "secure", True) else "http"
            image_url = (
                f"{protocol}://{self.minio_endpoint}/"
                f"{self.bucket_name}/{main_path}"
            )

            logger.info(f"MinIO uploaded successfully: {main_path}")

            return {
                "image_url": image_url,
                "thumbnail_url": image_url,
                "filename": main_path,
                "thumbnail_filename": main_path,
            }

        except Exception as e:
            logger.warning(f"MinIO upload failed ({e}). Falling back to local disk storage.")
            return self._upload_local(
                main_bytes=main_bytes,
                main_path=main_path,
            )

    async def upload_image_from_bytes(
        self,
        image_bytes: bytes,
        folder: str = "general",
    ) -> dict:
        """Upload raw image bytes directly to MinIO (no UploadFile needed)."""
        max_bytes = settings.MAX_IMAGE_SIZE_MB * 1024 * 1024
        if len(image_bytes) > max_bytes:
            raise ValueError(
                f"Image size exceeds {settings.MAX_IMAGE_SIZE_MB}MB limit"
            )

        main_bytes = self._process_image(image_bytes)
        file_id = str(uuid.uuid4())
        main_filename = f"{folder}/{file_id}.jpg"

        return await self._upload_minio(
            main_bytes=main_bytes,
            main_path=main_filename,
        )

    async def delete_image(self, filename: str):
        try:
            self.minio_client.remove_object(
                self.bucket_name,
                filename
            )

        except Exception as e:
            logger.exception(
                f"Failed to delete image from MinIO: {e}"
            )
            raise