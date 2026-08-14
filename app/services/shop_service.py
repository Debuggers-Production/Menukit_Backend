"""Shop management service."""

import uuid
from typing import Optional

from slugify import slugify
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.shop import Shop
from app.models.shop_settings import ShopSettings
from app.models.theme_settings import ThemeSettings
from app.models.activity_log import ActivityLog
from app.core.exceptions import NotFoundException, ConflictException


class ShopService:
    """Handles shop CRUD operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _generate_unique_slug(self, name: str) -> str:
        """Generate a unique slug from the shop name."""
        base_slug = slugify(name)
        slug = base_slug
        counter = 1

        while True:
            result = await self.db.execute(select(Shop).where(Shop.slug == slug))
            if not result.scalar_one_or_none():
                return slug
            slug = f"{base_slug}-{counter}"
            counter += 1

    async def create_shop(self, user_id: uuid.UUID, data: dict) -> Shop:
        """Create a new shop for a user."""
        # Check if user already has a shop
        result = await self.db.execute(select(Shop).where(Shop.user_id == user_id))
        existing = result.scalar_one_or_none()
        if existing:
            raise ConflictException("You already have a shop. Update it instead.")

        slug = await self._generate_unique_slug(data["name"])

        shop = Shop(
            user_id=user_id,
            slug=slug,
            **data,
        )
        self.db.add(shop)
        await self.db.flush()

        # Create default settings
        settings = ShopSettings(shop_id=shop.id)
        self.db.add(settings)
        shop.settings = settings

        # Create default theme
        theme = ThemeSettings(shop_id=shop.id)
        self.db.add(theme)
        shop.theme = theme

        # Log activity
        activity = ActivityLog(
            user_id=user_id,
            action="shop_create",
            details=f"Created shop: {shop.name}",
        )
        self.db.add(activity)

        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(shop)
        return shop

    async def get_shop_by_user(self, user_id: uuid.UUID) -> Optional[Shop]:
        """Get shop owned by user."""
        result = await self.db.execute(
            select(Shop)
            .options(selectinload(Shop.settings), selectinload(Shop.theme))
            .where(Shop.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_shop_by_slug(self, slug: str) -> Optional[Shop]:
        """Get shop by its URL slug."""
        result = await self.db.execute(
            select(Shop)
            .options(
                selectinload(Shop.settings),
                selectinload(Shop.theme),
                selectinload(Shop.categories),
            )
            .where(Shop.slug == slug, Shop.is_active == True)
        )
        return result.scalar_one_or_none()

    async def get_shop_by_id(self, shop_id: uuid.UUID) -> Optional[Shop]:
        """Get shop by its UUID."""
        result = await self.db.execute(
            select(Shop)
            .options(
                selectinload(Shop.settings),
                selectinload(Shop.theme),
                selectinload(Shop.categories),
            )
            .where(Shop.id == shop_id, Shop.is_active == True)
        )
        return result.scalar_one_or_none()

    async def update_shop(self, user_id: uuid.UUID, data: dict) -> Shop:
        """Update shop details."""
        shop = await self.get_shop_by_user(user_id)
        if not shop:
            raise NotFoundException("Shop not found")

        name_changed = "name" in data and data["name"] and data["name"] != shop.name

        for key, value in data.items():
            if hasattr(shop, key):
                setattr(shop, key, value)

        # If name changed, regenerate slug
        if name_changed:
            shop.slug = await self._generate_unique_slug(data["name"])

        # Log activity
        activity = ActivityLog(
            user_id=user_id,
            action="shop_update",
            details=f"Updated shop: {shop.name}",
        )
        self.db.add(activity)

        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(shop)
        return shop

    async def update_theme(self, user_id: uuid.UUID, data: dict) -> ThemeSettings:
        """Update theme settings."""
        shop = await self.get_shop_by_user(user_id)
        if not shop:
            raise NotFoundException("Shop not found")

        if not shop.theme:
            shop.theme = ThemeSettings(shop_id=shop.id)
            self.db.add(shop.theme)
            await self.db.flush()

        for key, value in data.items():
            if value is not None and hasattr(shop.theme, key):
                setattr(shop.theme, key, value)

        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(shop)
        return shop.theme

    async def update_settings(self, user_id: uuid.UUID, data: dict) -> ShopSettings:
        """Update shop settings."""
        shop = await self.get_shop_by_user(user_id)
        if not shop:
            raise NotFoundException("Shop not found")

        if not shop.settings:
            shop.settings = ShopSettings(shop_id=shop.id)
            self.db.add(shop.settings)
            await self.db.flush()

        bank_acc = data.get("bank_account_number")
        ifsc = data.get("ifsc_code")
        ben_name = data.get("beneficiary_name")

        import re
        from fastapi import HTTPException
        from app.core.config import get_settings

        # 1. Format Validation for Bank Details if they are being updated
        if bank_acc:
            if not ifsc or not ben_name:
                raise HTTPException(status_code=400, detail="Bank Account, IFSC, and Beneficiary Name are all required to setup payments.")
            if not re.match(r"^[A-Z]{4}0[A-Z0-9]{6}$", ifsc):
                raise HTTPException(status_code=400, detail="Invalid IFSC Code format.")
            if not bank_acc.isdigit() or len(bank_acc) < 9 or len(bank_acc) > 18:
                raise HTTPException(status_code=400, detail="Invalid Bank Account Number.")

        # 1b. Validate online_payments_enabled
        if data.get("online_payments_enabled") is True:
            status = shop.settings.razorpay_route_status
            if status not in ["activated", "active"]:
                raise HTTPException(status_code=400, detail="Cannot enable online payments until your settlement account is fully verified.")

        # 2. Update and Encrypt fields
        for key, value in data.items():
            if key == "bank_account_number":
                if value:
                    from cryptography.fernet import Fernet
                    import base64
                    import hashlib
                    secret = get_settings().SECRET_KEY
                    f_key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
                    cipher = Fernet(f_key)
                    shop.settings.encrypted_bank_account = cipher.encrypt(value.encode()).decode()
                    shop.settings.bank_account_last4 = value[-4:]
            elif value is not None and hasattr(shop.settings, key):
                setattr(shop.settings, key, value)

        # 3. Onboard to Razorpay Route
        needs_new_account = False
        app_settings = get_settings()
        if not app_settings.RAZORPAY_KEY_ID or not app_settings.RAZORPAY_KEY_SECRET:
            print("Warning: RAZORPAY_KEY_ID or SECRET is missing in environment variables.")
        else:
            import razorpay
            client = razorpay.Client(auth=(app_settings.RAZORPAY_KEY_ID, app_settings.RAZORPAY_KEY_SECRET))
            
            if shop.settings.razorpay_account_id:
                print(f"DEBUG: Shop already has a verified Razorpay Route Account: {shop.settings.razorpay_account_id}")
                if bank_acc:
                    print("DEBUG: New bank details detected. Auto-forwarding to Razorpay V2 API...")
                    class MockDataUpdate:
                        account_number = bank_acc
                        ifsc_code = ifsc
                        beneficiary_name = ben_name
                    try:
                        await self.update_razorpay_bank_account(user_id, MockDataUpdate())
                    except Exception as update_err:
                        print(f"DEBUG: Failed auto-forwarding bank details to Razorpay: {update_err}")
                        raise update_err
            elif bank_acc:
                print("DEBUG: New bank details detected and no Razorpay account exists. Auto-creating...")
                class MockAddress:
                    street = shop.address or "Shop Address"
                    city = shop.city or "Chennai"
                    state = "Tamil Nadu"
                    postal_code = 600001
                    country = "IN"

                class MockDataCreate:
                    owner_name = ben_name
                    owner_email = getattr(shop.user, "email", f"vendor_{shop.id}@menukit.com") if hasattr(shop, "user") and shop.user else f"vendor_{shop.id}@menukit.com"
                    owner_phone = shop.phone or "9999999999"
                    business_type = "individual"
                    business_address = MockAddress()
                    
                    class MockBankAccount:
                        account_number = bank_acc
                        ifsc_code = ifsc
                        beneficiary_name = ben_name
                    bank_account = MockBankAccount()

                try:
                    await self.create_razorpay_linked_account(user_id, MockDataCreate())
                    # Refresh shop to get the newly attached razorpay account id
                    await self.db.refresh(shop.settings)
                except Exception as create_err:
                    print(f"DEBUG: Failed to auto-create Razorpay account: {create_err}")
                    raise create_err

        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(shop)
        return shop.settings

    async def create_razorpay_linked_account(self, user_id: uuid.UUID, data: any) -> dict:
        """Create a Razorpay Route Linked Account using V2 API."""
        from fastapi import HTTPException
        import requests
        from app.core.config import get_settings
        
        result = await self.db.execute(
            select(Shop).options(selectinload(Shop.settings)).where(Shop.user_id == user_id)
        )
        shop = result.scalar_one_or_none()
        if not shop:
            raise HTTPException(status_code=404, detail="Shop not found")
            
        if shop.settings and shop.settings.razorpay_account_id:
            raise HTTPException(status_code=400, detail=f"Shop already has a Razorpay account linked: {shop.settings.razorpay_account_id}")
            
        app_settings = get_settings()
        if not app_settings.RAZORPAY_KEY_ID or not app_settings.RAZORPAY_KEY_SECRET:
            raise HTTPException(status_code=500, detail="Razorpay credentials missing on server")
            
        # 1. POST /v2/accounts
        account_url = "https://api.razorpay.com/v2/accounts"
        account_payload = {
            "email": data.owner_email,
            "phone": data.owner_phone,
            "legal_business_name": data.owner_name[:50],
            "business_type": data.business_type,
            "customer_facing_business_name": shop.name[:50],
            "type": "route",
            "profile": {
                "category": "food",
                "subcategory": "restaurant",
                "addresses": {
                    "registered": {
                        "street1": data.business_address.street[:50],
                        "street2": "N/A",
                        "city": data.business_address.city,
                        "state": data.business_address.state,
                        "postal_code": data.business_address.postal_code,
                        "country": data.business_address.country
                    }
                }
            }
        }
        
        try:
            acc_res = requests.post(
                account_url,
                json=account_payload,
                auth=(app_settings.RAZORPAY_KEY_ID, app_settings.RAZORPAY_KEY_SECRET),
                timeout=10
            )
        except requests.exceptions.RequestException as e:
            raise HTTPException(status_code=502, detail=f"Failed to connect to Razorpay: {str(e)}")
            
        if acc_res.status_code >= 400:
            err_data = acc_res.json() if acc_res.content else {}
            err_msg = err_data.get("error", {}).get("description", "Failed to create Razorpay account")
            raise HTTPException(status_code=400, detail=f"Razorpay API Error: {err_msg}")
            
        acc_data = acc_res.json()
        account_id = acc_data.get("id")
        
        # 2. POST /v2/accounts/{account_id}/products (attach route product & bank)
        product_id = None
        status = "under_review"
        try:
            prod_url = f"https://api.razorpay.com/v2/accounts/{account_id}/products"
            prod_payload = {
                "product_name": "route",
                "tnc_accepted": True
            }
            prod_res = requests.post(
                prod_url,
                json=prod_payload,
                auth=(app_settings.RAZORPAY_KEY_ID, app_settings.RAZORPAY_KEY_SECRET),
                timeout=10
            )
            if prod_res.status_code < 400:
                prod_data = prod_res.json()
                product_id = prod_data.get("id")
                status = prod_data.get("activation_status", "under_review")
                
                # Now PATCH the bank details
                patch_url = f"https://api.razorpay.com/v2/accounts/{account_id}/products/{product_id}"
                patch_payload = {
                    "settlements": {
                        "account_number": data.bank_account.account_number,
                        "ifsc_code": data.bank_account.ifsc_code,
                        "beneficiary_name": data.bank_account.beneficiary_name
                    },
                    "tnc_accepted": True
                }
                patch_res = requests.patch(
                    patch_url,
                    json=patch_payload,
                    auth=(app_settings.RAZORPAY_KEY_ID, app_settings.RAZORPAY_KEY_SECRET),
                    timeout=10
                )
                if patch_res.status_code >= 400:
                    print(f"DEBUG: Failed to PATCH bank details: {patch_res.text}")
        except Exception as e:
            print(f"DEBUG: Product configuration warning: {e}")
            
        # 3. Store in DB
        if not shop.settings:
            shop.settings = ShopSettings(shop_id=shop.id)
            self.db.add(shop.settings)
            
        shop.settings.razorpay_account_id = account_id
        shop.settings.razorpay_product_id = product_id
        shop.settings.razorpay_route_status = status
        
        from cryptography.fernet import Fernet
        import base64
        import hashlib
        secret = app_settings.SECRET_KEY
        f_key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
        cipher = Fernet(f_key)
        
        shop.settings.encrypted_bank_account = cipher.encrypt(data.bank_account.account_number.encode()).decode()
        shop.settings.bank_account_last4 = data.bank_account.account_number[-4:]
        shop.settings.ifsc_code = data.bank_account.ifsc_code
        shop.settings.beneficiary_name = data.bank_account.beneficiary_name
        
        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(shop)
        
        return {
            "success": True,
            "message": "Razorpay Route account created successfully",
            "razorpay_account_id": account_id,
            "razorpay_product_id": product_id,
            "status": status
        }

    async def update_razorpay_bank_account(self, user_id: uuid.UUID, data: any) -> dict:
        """Update Razorpay Route Bank Account via V2 API."""
        from fastapi import HTTPException
        import requests
        from app.core.config import get_settings
        
        # 1. Verify shop and owner
        result = await self.db.execute(
            select(Shop).options(selectinload(Shop.settings)).where(Shop.user_id == user_id)
        )
        shop = result.scalar_one_or_none()
        if not shop:
            raise HTTPException(status_code=404, detail="Shop not found")
            
        if not shop.settings or not shop.settings.razorpay_account_id:
            raise HTTPException(status_code=400, detail="Razorpay account is not configured for this shop")
            
        app_settings = get_settings()
        if not app_settings.RAZORPAY_KEY_ID or not app_settings.RAZORPAY_KEY_SECRET:
            raise HTTPException(status_code=500, detail="Razorpay credentials missing on server")
            
        # Fetch product ID if missing
        if not shop.settings.razorpay_product_id:
            try:
                fetch_url = f"https://api.razorpay.com/v2/accounts/{shop.settings.razorpay_account_id}/products"
                fetch_res = requests.post(
                    fetch_url,
                    json={"product_name": "route", "tnc_accepted": True},
                    auth=(app_settings.RAZORPAY_KEY_ID, app_settings.RAZORPAY_KEY_SECRET)
                )
                if fetch_res.status_code < 400:
                    shop.settings.razorpay_product_id = fetch_res.json().get("id")
            except Exception as e:
                print(f"DEBUG: Failed to fetch missing product ID: {e}")
                
        if not shop.settings.razorpay_product_id:
            raise HTTPException(status_code=400, detail="Could not retrieve Razorpay product ID to update bank account")
            
        # 2. Call Razorpay V2 API
        url = f"https://api.razorpay.com/v2/accounts/{shop.settings.razorpay_account_id}/products/{shop.settings.razorpay_product_id}"
        payload = {
            "settlements": {
                "account_number": data.account_number,
                "ifsc_code": data.ifsc_code,
                "beneficiary_name": data.beneficiary_name
            },
            "tnc_accepted": True
        }
        
        try:
            response = requests.patch(
                url, 
                json=payload, 
                auth=(app_settings.RAZORPAY_KEY_ID, app_settings.RAZORPAY_KEY_SECRET),
                timeout=10
            )
        except requests.exceptions.RequestException as e:
            raise HTTPException(status_code=502, detail=f"Failed to connect to Razorpay: {str(e)}")
            
        if response.status_code >= 400:
            error_data = response.json() if response.content else {}
            error_msg = error_data.get("error", {}).get("description", "Unknown Razorpay error")
            raise HTTPException(status_code=400, detail=f"Razorpay API Error: {error_msg}")
            
        response_data = response.json()
        new_status = response_data.get("activation_status", "under_review")
        
        # 3. Update local DB
        shop.settings.razorpay_route_status = new_status
        
        from cryptography.fernet import Fernet
        import base64
        import hashlib
        secret = app_settings.SECRET_KEY
        f_key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
        cipher = Fernet(f_key)
        
        shop.settings.encrypted_bank_account = cipher.encrypt(data.account_number.encode()).decode()
        shop.settings.bank_account_last4 = data.account_number[-4:]
        shop.settings.ifsc_code = data.ifsc_code
        shop.settings.beneficiary_name = data.beneficiary_name
        
        await self.db.flush()
        
        return {
            "success": True,
            "message": "Bank account update submitted successfully",
            "razorpay_account_id": shop.settings.razorpay_account_id,
            "status": new_status
        }

    async def get_razorpay_account_status(self, user_id: uuid.UUID) -> dict:
        """Fetch real-time Razorpay account/product status and update database."""
        from fastapi import HTTPException
        import requests
        from app.core.config import get_settings

        result = await self.db.execute(
            select(Shop).options(selectinload(Shop.settings)).where(Shop.user_id == user_id)
        )
        shop = result.scalar_one_or_none()
        if not shop:
            raise HTTPException(status_code=404, detail="Shop not found")

        if not shop.settings or not shop.settings.razorpay_account_id:
            return {
                "razorpay_account_id": None,
                "razorpay_product_id": None,
                "status": "not_configured",
                "is_verified": False,
                "message": "No Razorpay account linked yet"
            }

        app_settings = get_settings()
        if not app_settings.RAZORPAY_KEY_ID or not app_settings.RAZORPAY_KEY_SECRET:
            raise HTTPException(status_code=500, detail="Razorpay credentials missing on server")

        account_id = shop.settings.razorpay_account_id
        product_id = shop.settings.razorpay_product_id
        status = shop.settings.razorpay_route_status or "under_review"

        # Query the V2 product endpoint to get Route activation_status
        if product_id:
            try:
                prod_url = f"https://api.razorpay.com/v2/accounts/{account_id}/products/{product_id}"
                res = requests.get(
                    prod_url,
                    auth=(app_settings.RAZORPAY_KEY_ID, app_settings.RAZORPAY_KEY_SECRET),
                    timeout=10
                )
                if res.status_code < 400:
                    prod_data = res.json()
                    status = prod_data.get("activation_status", status)
            except Exception as e:
                print(f"DEBUG: Failed to fetch product status: {e}")
        else:
            # Fallback if no product_id is saved
            try:
                acc_url = f"https://api.razorpay.com/v2/accounts/{account_id}"
                res = requests.get(
                    acc_url,
                    auth=(app_settings.RAZORPAY_KEY_ID, app_settings.RAZORPAY_KEY_SECRET),
                    timeout=10
                )
                if res.status_code < 400:
                    acc_data = res.json()
                    status = acc_data.get("status", status)
            except Exception as e:
                print(f"DEBUG: Failed to fetch account status: {e}")


        # Update local status in DB
        shop.settings.razorpay_route_status = status
        await self.db.flush()

        return {
            "razorpay_account_id": account_id,
            "razorpay_product_id": product_id,
            "status": status,
            "is_verified": status == "active" or status == "activated",
            "message": "Razorpay account is verified and active" if (status == "active" or status == "activated") else "Verification in progress"
        }

    async def get_all_shops(self, page: int = 1, page_size: int = 20) -> dict:
        """Get all shops (admin)."""
        offset = (page - 1) * page_size
        result = await self.db.execute(
            select(Shop)
            .options(selectinload(Shop.settings), selectinload(Shop.theme))
            .offset(offset)
            .limit(page_size)
        )
        shops = result.scalars().all()

        count_result = await self.db.execute(select(func.count(Shop.id)))
        total = count_result.scalar()

        return {
            "items": shops,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
        }

    async def toggle_shop(self, shop_id: uuid.UUID) -> Shop:
        """Enable/disable a shop (admin)."""
        result = await self.db.execute(select(Shop).where(Shop.id == shop_id))
        shop = result.scalar_one_or_none()
        if not shop:
            raise NotFoundException("Shop not found")

        shop.is_active = not shop.is_active
        await self.db.flush()
        await self.db.commit()
        await self.db.refresh(shop)
        return shop

