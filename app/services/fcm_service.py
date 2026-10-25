"""Firebase Cloud Messaging (FCM) Service for Push Notifications.

Supports Web (Desktop/Laptop Chrome, Edge, Safari, Firefox),
Android (Chrome, Edge, PWA), and iOS (Safari iOS 16.4+, PWA, APNs).
"""

import os
import json
import logging
import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete

import firebase_admin
from firebase_admin import credentials, messaging

from app.core.config import get_settings
from app.models.device_token import DeviceToken
from app.database.session import async_session_factory

logger = logging.getLogger(__name__)

def _safe_print(text: str) -> None:
    try:
        print(text)
    except Exception:
        try:
            print(text.encode('ascii', 'replace').decode('ascii'))
        except Exception:
            pass


# Global singleton app reference
_firebase_app: Optional[firebase_admin.App] = None
_firebase_init_attempted: bool = False


def get_firebase_app() -> Optional[firebase_admin.App]:
    """Initialize or return existing Firebase Admin App instance."""
    global _firebase_app, _firebase_init_attempted
    if _firebase_app is not None:
        return _firebase_app
    if _firebase_init_attempted:
        return _firebase_app

    _firebase_init_attempted = True
    settings = get_settings()

    if not getattr(settings, "FCM_ENABLED", True):
        logger.info("[FCM] Push notifications disabled via FCM_ENABLED=False")
        return None

    try:
        # Check if already initialized by another module
        _firebase_app = firebase_admin.get_app()
        logger.info("[FCM] Using existing Firebase Admin App")
        return _firebase_app
    except ValueError:
        pass

    cred = None
    # 1. Check raw JSON string in environment variable
    cred_json_str = getattr(settings, "FIREBASE_CREDENTIALS_JSON", None)
    if cred_json_str and cred_json_str.strip():
        try:
            cert_dict = json.loads(cred_json_str.strip())
            cred = credentials.Certificate(cert_dict)
            logger.info("[FCM] Loaded Firebase credentials from FIREBASE_CREDENTIALS_JSON")
        except Exception as e:
            logger.error(f"[FCM] Failed to parse FIREBASE_CREDENTIALS_JSON: {e}")

    # 2. Check service account file path
    if cred is None:
        cred_path = getattr(settings, "FIREBASE_CREDENTIALS_PATH", None)
        if cred_path and cred_path.strip():
            candidate_paths = [
                cred_path.strip(),
                os.path.join(os.getcwd(), cred_path.strip()),
                os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), cred_path.strip()),
            ]
            for p in candidate_paths:
                if os.path.isfile(p):
                    try:
                        cred = credentials.Certificate(p)
                        logger.info(f"[FCM] Loaded Firebase credentials from file: {p}")
                        break
                    except Exception as e:
                        logger.error(f"[FCM] Error loading credentials file {p}: {e}")

    # 3. Check Google Application Default Credentials or Project ID
    if cred is None:
        project_id = getattr(settings, "FIREBASE_PROJECT_ID", None)
        if project_id and project_id.strip():
            try:
                cred = credentials.ApplicationDefault()
                logger.info("[FCM] Using Google Application Default Credentials")
            except Exception:
                cred = None

    if cred is not None:
        try:
            _firebase_app = firebase_admin.initialize_app(cred)
            logger.info("[FCM] Firebase Admin App initialized successfully")
        except Exception as e:
            logger.error(f"[FCM] Failed to initialize Firebase App: {e}")
            _firebase_app = None
    else:
        logger.warning(
            "[FCM] Firebase credentials not configured. FCM push notifications will be skipped. "
            "To enable, set FIREBASE_CREDENTIALS_PATH or FIREBASE_CREDENTIALS_JSON in .env."
        )

    return _firebase_app


class FCMService:
    """Service to handle FCM device registration and push notification dispatch."""

    def __init__(self, db: Optional[AsyncSession] = None):
        self.db = db
        self.app = get_firebase_app()

    @classmethod
    def is_configured(cls) -> bool:
        """Returns True if Firebase Admin SDK is ready to send notifications."""
        return get_firebase_app() is not None

    async def register_device(
        self,
        token: str,
        shop_id: Optional[uuid.UUID] = None,
        user_id: Optional[uuid.UUID] = None,
        customer_id: Optional[uuid.UUID] = None,
        customer_phone: Optional[str] = None,
        platform: str = "web",
        device_type: Optional[str] = "desktop",
        browser: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> DeviceToken:
        """Register or update an FCM device token in the database."""
        async def _do_register(session: AsyncSession) -> DeviceToken:
            stmt = select(DeviceToken).where(DeviceToken.token == token)
            result = await session.execute(stmt)
            device = result.scalar_one_or_none()

            cleaned_phone = None
            if customer_phone:
                cleaned_phone = "".join(c for c in str(customer_phone) if c.isdigit())[-10:]

            if device:
                if shop_id:
                    device.shop_id = shop_id
                if user_id:
                    device.user_id = user_id
                if customer_id:
                    device.customer_id = customer_id
                if cleaned_phone:
                    device.customer_phone = cleaned_phone
                device.platform = platform or device.platform
                device.device_type = device_type or device.device_type
                device.browser = browser or device.browser
                device.user_agent = user_agent or device.user_agent
                device.is_active = True
                device.updated_at = datetime.now(timezone.utc)
            else:
                device = DeviceToken(
                    token=token,
                    shop_id=shop_id,
                    user_id=user_id,
                    customer_id=customer_id,
                    customer_phone=cleaned_phone,
                    platform=platform or "web",
                    device_type=device_type or "desktop",
                    browser=browser,
                    user_agent=user_agent,
                    is_active=True,
                )
                session.add(device)

            await session.commit()
            await session.refresh(device)
            _safe_print(f"\033[92m[FCM REGISTERED DEVICE]\033[0m Shop: {shop_id} | Phone: {cleaned_phone} | Platform: {platform} | Token: {token[:25]}...")
            logger.info(f"[FCM] Device registered (shop_id={shop_id}, phone={cleaned_phone}, platform={platform})")
            return device

        if self.db is not None:
            return await _do_register(self.db)
        else:
            async with async_session_factory() as session:
                return await _do_register(session)

    async def unregister_device(self, token: str) -> bool:
        """Deactivate or remove a device token upon logout."""
        async def _do_unregister(session: AsyncSession) -> bool:
            stmt = update(DeviceToken).where(DeviceToken.token == token).values(is_active=False)
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount > 0

        if self.db is not None:
            return await _do_unregister(self.db)
        else:
            async with async_session_factory() as session:
                return await _do_unregister(session)

    def _build_message(
        self,
        token: str,
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
        url: Optional[str] = None,
        notification_type: str = "DEFAULT",
    ) -> messaging.Message:
        """Build a multiplatform FCM Message (Web Push, Android, iOS Safari / APNs)."""
        data_payload = {
            "title": str(title),
            "body": str(body),
            "type": str(notification_type),
            "url": str(url or "/"),
            "timestamp": str(int(datetime.now(timezone.utc).timestamp())),
        }
        if data:
            for k, v in data.items():
                if v is not None:
                    data_payload[str(k)] = str(v)

        click_url = url or "/"

        webpush_fcm_options = None
        if click_url.startswith("https://"):
            webpush_fcm_options = messaging.WebpushFCMOptions(link=click_url)

        # Web Push configuration (for Chrome, Edge, Safari on macOS & iOS 16.4+, Android browsers)
        tag_id = (data.get("order_id") if data and data.get("order_id") else None) or int(datetime.now(timezone.utc).timestamp() * 1000)
        webpush_config = messaging.WebpushConfig(
            headers={
                "Urgency": "high",
            },
            notification=messaging.WebpushNotification(
                title=title,
                body=body,
                icon="/pwa-192x192.png",
                badge="/pwa-192x192.png",
                tag=f"menukit-{notification_type.lower()}-{tag_id}",
                require_interaction=True,
                vibrate=[200, 100, 200],
                data={"url": click_url, **data_payload},
            ),
            fcm_options=webpush_fcm_options,
        )

        # Android configuration
        android_config = messaging.AndroidConfig(
            priority="high",
            notification=messaging.AndroidNotification(
                title=title,
                body=body,
                icon="ic_notification",
                sound="default",
                channel_id="menukit_orders",
                click_action=click_url,
            ),
        )

        # iOS APNs configuration (Web Push to iOS Safari or native app)
        apns_config = messaging.APNSConfig(
            headers={
                "apns-priority": "10",
            },
            payload=messaging.APNSPayload(
                aps=messaging.Aps(
                    alert=messaging.ApsAlert(title=title, body=body),
                    sound="default",
                    badge=1,
                    content_available=True,
                ),
                custom_data={"url": click_url},
            ),
        )

        return messaging.Message(
            token=token,
            notification=messaging.Notification(title=title, body=body),
            data=data_payload,
            webpush=webpush_config,
            android=android_config,
            apns=apns_config,
        )

    async def _send_to_tokens(
        self,
        tokens: List[str],
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
        url: Optional[str] = None,
        notification_type: str = "DEFAULT",
    ) -> Dict[str, Any]:
        """Send push notifications to multiple tokens and automatically prune invalid tokens."""
        if not tokens:
            return {"success_count": 0, "failure_count": 0, "total": 0}

        app = get_firebase_app()
        if not app:
            logger.info(f"[FCM] Skipped sending '{title}' to {len(tokens)} token(s) (FCM not configured)")
            return {"success_count": 0, "failure_count": 0, "total": len(tokens), "skipped": True}

        messages = [
            self._build_message(
                token=token,
                title=title,
                body=body,
                data=data,
                url=url,
                notification_type=notification_type,
            )
            for token in tokens
        ]

        success_count = 0
        failure_count = 0
        tokens_to_deactivate = []

        # Batch in chunks of 500 (Firebase Admin maximum)
        chunk_size = 500
        for i in range(0, len(messages), chunk_size):
            chunk = messages[i : i + chunk_size]
            try:
                response = messaging.send_each(chunk, app=app)
                success_count += response.success_count
                failure_count += response.failure_count

                for idx, resp in enumerate(response.responses):
                    if not resp.success:
                        error = resp.exception
                        orig_token = chunk[idx].token
                        error_code = getattr(error, "code", None)
                        # Identify stale/expired tokens to clean up
                        if isinstance(error, (messaging.UnregisteredError, messaging.SenderIdMismatchError)) or error_code in (
                            "registration-token-not-registered",
                            "invalid-argument",
                        ):
                            tokens_to_deactivate.append(orig_token)
            except Exception as e:
                logger.error(f"[FCM] Batch send failed: {e}")
                failure_count += len(chunk)

        # Deactivate stale tokens
        if tokens_to_deactivate:
            try:
                async with async_session_factory() as session:
                    await session.execute(
                        update(DeviceToken)
                        .where(DeviceToken.token.in_(tokens_to_deactivate))
                        .values(is_active=False)
                    )
                    await session.commit()
                    logger.info(f"[FCM] Deactivated {len(tokens_to_deactivate)} stale tokens")
            except Exception as e:
                logger.error(f"[FCM] Failed to deactivate stale tokens: {e}")

        _safe_print(f"\033[92m[FCM SENT RESULT]\033[0m Success: {success_count} | Failed: {failure_count} | Title: '{title}'")
        logger.info(f"[FCM] Sent '{title}' -> Success: {success_count}, Fail: {failure_count}")
        return {
            "success_count": success_count,
            "failure_count": failure_count,
            "total": len(tokens),
        }

    async def send_to_shop(
        self,
        shop_id: uuid.UUID,
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
        url: Optional[str] = "/orders",
        notification_type: str = "DEFAULT",
    ) -> Dict[str, Any]:
        """Send push notification to all active devices registered for a specific shop."""
        tokens = []
        try:
            async with async_session_factory() as session:
                from app.models.shop import Shop
                from app.models.employee import Employee
                from sqlalchemy import or_

                # Find the owner user_id of this shop
                shop_owner_id = None
                s_res = await session.execute(select(Shop.user_id).where(Shop.id == shop_id))
                s_row = s_res.fetchone()
                if s_row and s_row[0]:
                    shop_owner_id = s_row[0]

                # Find all employees belonging to this shop
                emp_res = await session.execute(
                    select(Employee.user_id).where(
                        Employee.shop_id == shop_id,
                        Employee.user_id.isnot(None)
                    )
                )
                emp_user_ids = [r[0] for r in emp_res.fetchall() if r[0]]

                # Match devices registered directly to this shop, the shop owner, or active shop employees
                conditions = [DeviceToken.shop_id == shop_id]
                if shop_owner_id:
                    conditions.append(DeviceToken.user_id == shop_owner_id)
                if emp_user_ids:
                    conditions.append(DeviceToken.user_id.in_(emp_user_ids))

                stmt = select(DeviceToken.token).where(
                    or_(*conditions),
                    DeviceToken.is_active == True,
                ).distinct()
                result = await session.execute(stmt)
                tokens = [row[0] for row in result.fetchall()]
        except Exception as db_err:
            logger.error(f"[FCM] Error querying shop device tokens: {db_err}")
            return {"success_count": 0, "failure_count": 0, "total": 0}

        _safe_print(f"\033[95m[FCM DISPATCH TO SHOP]\033[0m Shop: {shop_id} | Title: '{title}' | Devices Found: {len(tokens)}")

        if not tokens:
            _safe_print(f"\033[93m[FCM WARNING]\033[0m No active device tokens found in DB for shop {shop_id}! Notifications cannot be delivered until a device registers.")
            logger.debug(f"[FCM] No active device tokens found for shop {shop_id}")
            return {"success_count": 0, "failure_count": 0, "total": 0}

        return await self._send_to_tokens(
            tokens=tokens,
            title=title,
            body=body,
            data=data,
            url=url,
            notification_type=notification_type,
        )

    async def send_to_customer(
        self,
        customer_phone: str,
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
        url: Optional[str] = "/orders",
        notification_type: str = "ORDER_STATUS",
    ) -> Dict[str, Any]:
        """Send push notification to all active devices registered for a customer phone number."""
        if not customer_phone:
            return {"success_count": 0, "failure_count": 0, "total": 0}

        tokens = []
        try:
            last_10 = "".join(c for c in str(customer_phone) if c.isdigit())[-10:]
            async with async_session_factory() as session:
                stmt = select(DeviceToken.token).where(
                    DeviceToken.customer_phone == last_10,
                    DeviceToken.is_active == True,
                )
                result = await session.execute(stmt)
                tokens = [row[0] for row in result.fetchall()]
        except Exception as db_err:
            logger.error(f"[FCM] Error querying customer device tokens: {db_err}")
            return {"success_count": 0, "failure_count": 0, "total": 0}

        _safe_print(f"\033[95m[FCM DISPATCH TO CUSTOMER]\033[0m Phone: {customer_phone} | Title: '{title}' | Devices Found: {len(tokens)}")

        if not tokens:
            _safe_print(f"\033[93m[FCM WARNING]\033[0m No active device tokens found in DB for customer phone {customer_phone}!")
            logger.debug(f"[FCM] No active device tokens found for customer phone {customer_phone}")
            return {"success_count": 0, "failure_count": 0, "total": 0}

        return await self._send_to_tokens(
            tokens=tokens,
            title=title,
            body=body,
            data=data,
            url=url,
            notification_type=notification_type,
        )

    async def send_to_token(
        self,
        token: str,
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
        url: Optional[str] = "/",
        notification_type: str = "TEST",
    ) -> Dict[str, Any]:
        """Send direct push notification to a single device token (for test & verification)."""
        return await self._send_to_tokens(
            tokens=[token],
            title=title,
            body=body,
            data=data,
            url=url,
            notification_type=notification_type,
        )
