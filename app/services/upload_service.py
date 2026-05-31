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
        self.minio_endpoint = settings.MINIO_ENDPOINT
        self.bucket_name = settings.MINIO_BUCKET_NAME

        self.minio_client = Minio(
            self.minio_endpoint,
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=True
        )

        self._ensure_bucket_exists()

    def _ensure_bucket_exists(self):
        try:
            if not self.minio_client.bucket_exists(self.bucket_name):
                self.minio_client.make_bucket(self.bucket_name)

            logger.info(
                f"MinIO bucket '{self.bucket_name}' ready"
            )

        except S3Error as e:
            logger.exception(f"Failed to create bucket: {e}")
            raise

    def _process_image(self, image_data: bytes) -> Tuple[bytes, bytes]:
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

        main_bytes = main_buffer.getvalue()

        thumb_ratio = THUMBNAIL_WIDTH / img.width
        thumb_height = int(img.height * thumb_ratio)

        thumb = img.resize(
            (THUMBNAIL_WIDTH, thumb_height),
            Image.LANCZOS
        )

        thumb_buffer = BytesIO()

        thumb.save(
            thumb_buffer,
            format="JPEG",
            quality=70,
            optimize=True
        )

        thumb_bytes = thumb_buffer.getvalue()

        return main_bytes, thumb_bytes

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

        main_bytes, thumb_bytes = self._process_image(contents)

        file_id = str(uuid.uuid4())

        main_filename = f"{folder}/{file_id}.jpg"
        thumb_filename = f"{folder}/{file_id}_thumb.jpg"

        return await self._upload_minio(
            main_bytes=main_bytes,
            thumb_bytes=thumb_bytes,
            main_path=main_filename,
            thumb_path=thumb_filename,
        )

    async def _upload_minio(
        self,
        main_bytes: bytes,
        thumb_bytes: bytes,
        main_path: str,
        thumb_path: str,
    ) -> dict:

        try:

            logger.info(
                f"Uploaded successfully: {main_path}"
            )
            self.minio_client.put_object(
                bucket_name=self.bucket_name,
                object_name=main_path,
                data=BytesIO(main_bytes),
                length=len(main_bytes),
                content_type="image/jpeg",
            )

            self.minio_client.put_object(
                bucket_name=self.bucket_name,
                object_name=thumb_path,
                data=BytesIO(thumb_bytes),
                length=len(thumb_bytes),
                content_type="image/jpeg",
            )

            image_url = (
                f"http://{self.minio_endpoint}/"
                f"{self.bucket_name}/{main_path}"
            )

            thumbnail_url = (
                f"http://{self.minio_endpoint}/"
                f"{self.bucket_name}/{thumb_path}"
            )

            return {
                "image_url": image_url,
                "thumbnail_url": thumbnail_url,
                "filename": main_path,
                "thumbnail_filename": thumb_path,
            }

        except Exception as e:
            logger.exception(f"MinIO upload failed: {e}")
            raise RuntimeError(
                "Failed to upload image to MinIO"
            ) from e

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