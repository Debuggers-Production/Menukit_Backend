"""Service for Savings Scheme (Pandu) operations."""

import asyncio
import uuid
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional, List, Tuple, Dict, Any

from sqlalchemy import select, func, or_, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import hmac
import hashlib
import re

from app.models.scheme import Scheme, SchemeMember, SchemePayment, SchemeActivityLog
from app.models.customer import Customer
from app.models.membership import CustomerRetailerMembership
from app.models.shop import Shop
from app.models.shop_settings import ShopSettings
from app.core.config import get_settings
from app.core.pricing import calculate_order_pricing
from app.services.upload_service import UploadService
from app.utils.media import strip_image_base_url
from app.utils.phone import normalize_phone_with_country_code
from app.schemas.scheme import (
    SchemeCreate,
    SchemeUpdate,
    SchemeResponse,
    SchemeStats,
    SchemeMemberCreate,
    SchemeMemberResponse,
    SchemePaymentResponse,
    InstallmentScheduleItem,
    RecordPaymentRequest,
    PublicSchemeResponse,
    CustomerSchemePassResponse,
    SchemePaymentInitiateRequest,
    SchemePaymentInitiateResponse,
    SchemePaymentVerifyRequest,
    SchemeMemberDeleteOtpResponse,
    SchemeMemberDeleteRequest,
    SchemeMemberTransferRequest,
    SchemeActivityLogResponse,
)
from app.core.exceptions import NotFoundException, BadRequestException

logger = logging.getLogger(__name__)


class SchemeService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.upload_service = UploadService()

    async def _log_activity(
        self,
        shop_id: uuid.UUID,
        customer_name: str,
        customer_phone: str,
        action_type: str,
        scheme_title: str,
        scheme_id: Optional[uuid.UUID] = None,
        member_id: Optional[uuid.UUID] = None,
        member_number: Optional[str] = None,
        from_scheme_title: Optional[str] = None,
        to_scheme_title: Optional[str] = None,
        amount: Optional[Decimal | float] = None,
        installment_number: Optional[int] = None,
        paid_installments: Optional[int] = None,
        total_installments: Optional[int] = None,
        otp_verified: bool = False,
        notes: Optional[str] = None,
    ):
        """Append an immutable audit entry to scheme_activity_logs."""
        try:
            log_entry = SchemeActivityLog(
                id=uuid.uuid4(),
                shop_id=shop_id,
                scheme_id=scheme_id,
                member_id=member_id,
                customer_name=customer_name.strip(),
                customer_phone=customer_phone.strip(),
                member_number=member_number,
                action_type=action_type,
                scheme_title=scheme_title,
                from_scheme_title=from_scheme_title,
                to_scheme_title=to_scheme_title,
                amount=Decimal(str(amount)) if amount is not None else None,
                installment_number=installment_number,
                paid_installments=paid_installments,
                total_installments=total_installments,
                otp_verified=otp_verified,
                notes=notes,
            )
            self.db.add(log_entry)
        except Exception as log_err:
            logger.error(f"Failed to record scheme activity log: {log_err}")


    async def get_schemes(self, shop_id: uuid.UUID) -> List[SchemeResponse]:
        """Get all schemes for a shop with high-level statistics."""
        # Ensure any existing unlinked scheme members are synced to shop members
        await self.sync_scheme_members_to_shop_members(shop_id)

        stmt = (
            select(Scheme)
            .options(
                selectinload(Scheme.members).selectinload(SchemeMember.payments),
                selectinload(Scheme.payments),
            )
            .where(Scheme.shop_id == shop_id)
            .order_by(Scheme.created_at.desc())
        )
        res = await self.db.execute(stmt)
        schemes = list(res.scalars().all())

        results = []
        for s in schemes:
            stats = self._calculate_scheme_stats(s)
            results.append(
                SchemeResponse(
                    id=str(s.id),
                    shop_id=str(s.shop_id),
                    title=s.title,
                    description=s.description,
                    image_url=getattr(s, "image_url", None),
                    price=float(s.price),
                    frequency=s.frequency,
                    term_duration=s.term_duration,
                    term_unit=s.term_unit,
                    max_members=s.max_members,
                    items=s.items or [],
                    reward_type=getattr(s, "reward_type", "specific_items") or "specific_items",
                    reward_categories=getattr(s, "reward_categories", []) or [],
                    highlight_text=getattr(s, "highlight_text", None),
                    show_on_public_menu=s.show_on_public_menu,
                    status=s.status,
                    start_date=s.start_date,
                    end_date=s.end_date,
                    created_at=s.created_at,
                    updated_at=s.updated_at,
                    stats=stats,
                )
            )
        return results

    async def get_scheme(self, scheme_id: uuid.UUID, shop_id: uuid.UUID) -> SchemeResponse:
        """Get single scheme with stats."""
        stmt = (
            select(Scheme)
            .options(
                selectinload(Scheme.members).selectinload(SchemeMember.payments),
                selectinload(Scheme.payments),
            )
            .where(Scheme.id == scheme_id, Scheme.shop_id == shop_id)
        )
        res = await self.db.execute(stmt)
        scheme = res.scalar_one_or_none()
        if not scheme:
            raise NotFoundException("Scheme not found")

        stats = self._calculate_scheme_stats(scheme)
        return SchemeResponse(
            id=str(scheme.id),
            shop_id=str(scheme.shop_id),
            title=scheme.title,
            description=scheme.description,
            image_url=getattr(scheme, "image_url", None),
            price=float(scheme.price),
            frequency=scheme.frequency,
            term_duration=scheme.term_duration,
            term_unit=scheme.term_unit,
            max_members=scheme.max_members,
            items=scheme.items or [],
            reward_type=getattr(scheme, "reward_type", "specific_items") or "specific_items",
            reward_categories=getattr(scheme, "reward_categories", []) or [],
            highlight_text=getattr(scheme, "highlight_text", None),
            show_on_public_menu=scheme.show_on_public_menu,
            status=scheme.status,
            start_date=scheme.start_date,
            end_date=scheme.end_date,
            created_at=scheme.created_at,
            updated_at=scheme.updated_at,
            stats=stats,
        )

    async def create_scheme(self, shop_id: uuid.UUID, data: SchemeCreate) -> SchemeResponse:
        """Create a new scheme."""
        scheme = Scheme(
            id=uuid.uuid4(),
            shop_id=shop_id,
            title=data.title.strip(),
            description=data.description.strip() if data.description else None,
            image_url=strip_image_base_url(data.image_url) if data.image_url else None,
            price=data.price,
            frequency=data.frequency,
            term_duration=data.term_duration,
            term_unit=data.term_unit,
            max_members=data.max_members,
            items=[i.model_dump() for i in data.items],
            reward_type=data.reward_type or "specific_items",
            reward_categories=data.reward_categories or [],
            highlight_text=data.highlight_text.strip() if data.highlight_text else None,
            show_on_public_menu=data.show_on_public_menu,
            status=data.status,
            start_date=data.start_date or datetime.now(timezone.utc),
            end_date=data.end_date,
        )
        self.db.add(scheme)
        await self.db.commit()
        await self.db.refresh(scheme)
        return await self.get_scheme(scheme.id, shop_id)

    async def update_scheme(self, scheme_id: uuid.UUID, shop_id: uuid.UUID, data: SchemeUpdate) -> SchemeResponse:
        """Update an existing scheme."""
        stmt = (
            select(Scheme)
            .options(selectinload(Scheme.members))
            .where(Scheme.id == scheme_id, Scheme.shop_id == shop_id)
        )
        res = await self.db.execute(stmt)
        scheme = res.scalar_one_or_none()
        if not scheme:
            raise NotFoundException("Scheme not found")

        # Check if scheme has active customers
        active_members = [m for m in scheme.members if m.status == "active"]
        has_active_customers = len(active_members) > 0

        dump = data.model_dump(exclude_unset=True)

        # Handle scheme banner replacement or removal: delete previous image from storage
        if "image_url" in dump:
            raw_new_img = dump["image_url"]
            clean_new_img = strip_image_base_url(raw_new_img) if raw_new_img else None
            dump["image_url"] = clean_new_img

            old_img = getattr(scheme, "image_url", None)
            clean_old_img = strip_image_base_url(old_img) if old_img else None

            # If an old image existed and is being replaced or removed, purge it from storage
            if clean_old_img and clean_old_img != clean_new_img:
                try:
                    await self.upload_service.delete_image_by_url(clean_old_img)
                    logger.info(f"Purged previous scheme banner from storage: {clean_old_img}")
                except Exception as e:
                    logger.warning(f"Failed to delete old scheme banner: {e}")

        if has_active_customers:
            # When active customers exist, strictly allow only title and description updates
            restricted_fields = ["price", "frequency", "term_duration", "term_unit", "max_members", "items", "reward_type", "reward_categories"]
            for field in restricted_fields:
                if field in dump:
                    curr_val = getattr(scheme, field)
                    new_val = dump[field]
                    if field == "price":
                        if curr_val is not None and Decimal(str(curr_val)) != Decimal(str(new_val)):
                            raise BadRequestException(
                                "Cannot modify installment price because this scheme has active enrolled customers. Only title and description can be updated."
                            )
                    elif field == "items":
                        if new_val != curr_val:
                            raise BadRequestException(
                                "Cannot modify reward items because this scheme has active enrolled customers. Only title and description can be updated."
                            )
                    else:
                        if curr_val != new_val:
                            raise BadRequestException(
                                f"Cannot modify {field.replace('_', ' ')} because this scheme has active enrolled customers. Only title and description can be updated."
                            )

        if "items" in dump and dump["items"] is not None:
            dump["items"] = [i.model_dump() if hasattr(i, "model_dump") else i for i in dump["items"]]

        for k, v in dump.items():
            setattr(scheme, k, v)

        scheme.updated_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(scheme)
        return await self.get_scheme(scheme.id, shop_id)

    async def delete_scheme(self, scheme_id: uuid.UUID, shop_id: uuid.UUID) -> bool:
        """Delete a scheme."""
        stmt = (
            select(Scheme)
            .options(selectinload(Scheme.members))
            .where(Scheme.id == scheme_id, Scheme.shop_id == shop_id)
        )
        res = await self.db.execute(stmt)
        scheme = res.scalar_one_or_none()
        if not scheme:
            raise NotFoundException("Scheme not found")

        active_members = [m for m in scheme.members if m.status == "active"]
        if len(active_members) > 0:
            raise BadRequestException(
                "Cannot delete this scheme because it has active enrolled customers. You can mark it as closed or pause it instead."
            )
        if len(scheme.members) > 0:
            raise BadRequestException(
                "Cannot delete this scheme because customers are associated with it. You can mark it as closed instead."
            )

        # Delete banner image from storage if present
        old_banner = getattr(scheme, "image_url", None)
        if old_banner:
            try:
                await self.upload_service.delete_image_by_url(old_banner)
                logger.info(f"Purged scheme banner from storage upon deletion: {old_banner}")
            except Exception as e:
                logger.warning(f"Failed to delete scheme banner on delete: {e}")

        await self.db.delete(scheme)
        await self.db.commit()
        return True

    async def get_scheme_members(
        self, scheme_id: uuid.UUID, shop_id: uuid.UUID, search: Optional[str] = None
    ) -> List[SchemeMemberResponse]:
        """Get members of a scheme with installment payment progress."""
        # Ensure any unlinked scheme members are synced to shop members
        await self.sync_scheme_members_to_shop_members(shop_id)

        scheme_stmt = select(Scheme).where(Scheme.id == scheme_id, Scheme.shop_id == shop_id)
        scheme_res = await self.db.execute(scheme_stmt)
        scheme = scheme_res.scalar_one_or_none()
        if not scheme:
            raise NotFoundException("Scheme not found")

        query = (
            select(SchemeMember)
            .options(selectinload(SchemeMember.payments))
            .where(SchemeMember.scheme_id == scheme_id, SchemeMember.shop_id == shop_id)
        )

        if search and search.strip():
            clean = search.strip().lower()
            query = query.where(
                or_(
                    func.lower(SchemeMember.customer_name).contains(clean),
                    func.lower(SchemeMember.customer_phone).contains(clean),
                    func.lower(SchemeMember.member_number).contains(clean),
                )
            )

        query = query.order_by(SchemeMember.joined_at.desc())
        res = await self.db.execute(query)
        members = list(res.scalars().all())

        return [self._format_member_response(m, scheme) for m in members]

    async def sync_scheme_members_to_shop_members(self, shop_id: uuid.UUID) -> int:
        """
        Idempotently synchronize scheme members for a shop into the shop's customer members list.
        - Scheme members are placed into the "New" (auto-registered) member category (is_retailer_added=False),
          so the merchant can manage them via the "New" tab and click "Verify & Add".
        - Matches or creates global Customer records using phone variations with zero data loss.
        - Updates SchemeMember.customer_id.
        - Creates CustomerRetailerMembership with is_retailer_added=False.
        - If any scheme member was placed into Existing before manual verification, resets them to New.
        """
        try:
            # Query all scheme members for this shop
            stmt = select(SchemeMember).where(SchemeMember.shop_id == shop_id)
            res = await self.db.execute(stmt)
            scheme_members = list(res.scalars().all())

            if not scheme_members:
                return 0

            synced_count = 0
            for sm in scheme_members:
                phone_raw = (sm.customer_phone or "").strip()
                if not phone_raw:
                    continue

                normalized_phone = normalize_phone_with_country_code(phone_raw)
                # Ensure SchemeMember.customer_phone includes country code
                if sm.customer_phone != normalized_phone:
                    sm.customer_phone = normalized_phone
                    synced_count += 1

                clean_digits = "".join([c for c in phone_raw if c.isdigit()])
                last10 = clean_digits[-10:] if len(clean_digits) >= 10 else clean_digits
                phone_variants = list(set(filter(None, [
                    phone_raw,
                    normalized_phone,
                    clean_digits,
                    f"+{clean_digits}" if clean_digits else None,
                    f"+91{last10}" if last10 else None,
                    f"91{last10}" if last10 else None,
                    last10
                ])))

                cust = None
                if sm.customer_id:
                    cust = await self.db.get(Customer, sm.customer_id)

                if not cust and phone_variants:
                    cust_stmt = select(Customer).where(Customer.mobile_number.in_(phone_variants))
                    cust_res = await self.db.execute(cust_stmt)
                    matched_custs = list(cust_res.scalars().all())
                    if matched_custs:
                        # Prefer existing customer record whose mobile_number is already normalized
                        cust = next((c for c in matched_custs if c.mobile_number == normalized_phone), matched_custs[0])

                trimmed_name = (sm.customer_name or "").strip() or None
                trimmed_addr = (sm.customer_address or "").strip() or None

                if cust:
                    if sm.customer_id != cust.id:
                        sm.customer_id = cust.id
                        synced_count += 1
                    if trimmed_name and not cust.name:
                        cust.name = trimmed_name
                    if trimmed_addr and not cust.delivery_address:
                        cust.delivery_address = trimmed_addr

                    # Ensure existing Customer record has the normalized phone with country code
                    cust_norm = normalize_phone_with_country_code(cust.mobile_number)
                    if cust.mobile_number != cust_norm:
                        # Check if another customer already has this normalized phone
                        existing_norm_stmt = select(Customer).where(Customer.mobile_number == cust_norm)
                        existing_norm_res = await self.db.execute(existing_norm_stmt)
                        existing_norm_cust = existing_norm_res.scalars().first()
                        if existing_norm_cust and existing_norm_cust.id != cust.id:
                            # Re-link to existing customer with normalized number
                            sm.customer_id = existing_norm_cust.id
                            cust = existing_norm_cust
                            synced_count += 1
                        else:
                            cust.mobile_number = cust_norm
                            synced_count += 1
                else:
                    try:
                        new_cust = Customer(
                            id=uuid.uuid4(),
                            name=trimmed_name,
                            mobile_number=normalized_phone,
                            delivery_address=trimmed_addr,
                        )
                        self.db.add(new_cust)
                        await self.db.flush()
                        sm.customer_id = new_cust.id
                        cust = new_cust
                        synced_count += 1
                    except Exception as ce:
                        logger.warning(f"Sync: customer create failed for {normalized_phone}: {ce}")
                        cust_stmt = select(Customer).where(Customer.mobile_number.in_(phone_variants))
                        cust_res = await self.db.execute(cust_stmt)
                        matched_custs = list(cust_res.scalars().all())
                        if matched_custs:
                            cust = next((c for c in matched_custs if c.mobile_number == normalized_phone), matched_custs[0])
                            sm.customer_id = cust.id
                            cust_norm = normalize_phone_with_country_code(cust.mobile_number)
                            if cust.mobile_number != cust_norm:
                                try:
                                    cust.mobile_number = cust_norm
                                    synced_count += 1
                                except Exception:
                                    pass

                if not cust:
                    continue

                # Ensure shop membership exists in the "New" (auto-registered) category (is_retailer_added=False)
                mem_stmt = select(CustomerRetailerMembership).where(
                    CustomerRetailerMembership.customer_id == cust.id,
                    CustomerRetailerMembership.shop_id == shop_id,
                )
                mem_res = await self.db.execute(mem_stmt)
                membership = mem_res.scalar_one_or_none()

                if not membership:
                    new_mem = CustomerRetailerMembership(
                        id=uuid.uuid4(),
                        customer_id=cust.id,
                        shop_id=shop_id,
                        is_retailer_added=False,  # NEW MEMBER category!
                        customer_name=trimmed_name,
                        created_at=sm.joined_at if getattr(sm, 'joined_at', None) else None,
                    )
                    self.db.add(new_mem)
                    synced_count += 1
                else:
                    changed = False
                    # If this scheme member was unverified (notes != 'VERIFIED') but has is_retailer_added == True,
                    # place them into the "New" category (is_retailer_added = False)
                    if getattr(sm, 'notes', None) != 'VERIFIED' and membership.is_retailer_added is True:
                        membership.is_retailer_added = False
                        changed = True
                    if trimmed_name and not membership.customer_name:
                        membership.customer_name = trimmed_name
                        changed = True
                    if changed:
                        synced_count += 1

            if synced_count > 0:
                await self.db.commit()
                logger.info(f"Successfully synced {synced_count} scheme members to New category for shop {shop_id}")

            return synced_count
        except Exception as e:
            logger.error(f"Error in sync_scheme_members_to_shop_members for shop {shop_id}: {e}", exc_info=True)
            return 0

    async def lookup_customer(self, shop_id: uuid.UUID, phone: str, scheme_id: Optional[uuid.UUID] = None) -> Optional[dict]:
        """Lookup an existing customer by phone number to autofill details and check duplicate enrollment in scheme."""
        if not phone or not phone.strip():
            return None

        phone_clean = normalize_phone_with_country_code(phone)
        clean_digits = "".join([c for c in phone_clean if c.isdigit()])
        last10 = clean_digits[-10:] if len(clean_digits) >= 10 else clean_digits
        phone_variants = list(set(filter(None, [
            phone_clean,
            phone.strip(),
            clean_digits,
            f"+{clean_digits}" if clean_digits else None,
            f"+91{last10}" if last10 else None,
            f"91{last10}" if last10 else None,
            last10
        ])))

        found_name = None
        found_address = None
        customer_id = None

        # 1. Search Customer table
        cust_stmt = select(Customer).where(Customer.mobile_number.in_(phone_variants))
        cust_res = await self.db.execute(cust_stmt)
        cust = cust_res.scalars().first()
        if cust:
            customer_id = str(cust.id)
            if cust.name:
                found_name = cust.name
            if cust.delivery_address:
                found_address = cust.delivery_address

        # 2. Check CustomerRetailerMembership for this shop
        if cust:
            mem_stmt = select(CustomerRetailerMembership).where(
                CustomerRetailerMembership.customer_id == cust.id,
                CustomerRetailerMembership.shop_id == shop_id,
            )
            mem_res = await self.db.execute(mem_stmt)
            mem = mem_res.scalar_one_or_none()
            if mem and mem.customer_name and not found_name:
                found_name = mem.customer_name

        # 3. Check existing SchemeMember records for this shop
        sm_stmt = select(SchemeMember).where(
            SchemeMember.shop_id == shop_id,
            SchemeMember.customer_phone.in_(phone_variants)
        ).order_by(SchemeMember.created_at.desc())
        sm_res = await self.db.execute(sm_stmt)
        sm = sm_res.scalars().first()
        if sm:
            if not found_name and sm.customer_name:
                found_name = sm.customer_name
            if not found_address and sm.customer_address:
                found_address = sm.customer_address

        # 4. Check if customer is already enrolled in this specific scheme
        is_already_enrolled = False
        enrolled_member = None
        if scheme_id:
            dup_conditions = [SchemeMember.customer_phone.in_(phone_variants)]
            if cust:
                dup_conditions.append(SchemeMember.customer_id == cust.id)
            if last10 and len(last10) >= 10:
                dup_conditions.append(SchemeMember.customer_phone.like(f"%{last10}"))

            dup_stmt = select(SchemeMember).where(
                SchemeMember.scheme_id == scheme_id,
                or_(*dup_conditions)
            )
            dup_res = await self.db.execute(dup_stmt)
            enrolled_member = dup_res.scalars().first()
            if enrolled_member:
                is_already_enrolled = True
                if not found_name and enrolled_member.customer_name:
                    found_name = enrolled_member.customer_name
                if not found_address and enrolled_member.customer_address:
                    found_address = enrolled_member.customer_address

        if not found_name and not found_address and not customer_id and not is_already_enrolled:
            return None

        return {
            "found": True,
            "id": customer_id,
            "name": found_name,
            "phone": phone_clean,
            "address": found_address,
            "is_already_enrolled": is_already_enrolled,
            "enrolled_member_number": enrolled_member.member_number if enrolled_member else None,
            "enrolled_member_name": enrolled_member.customer_name if enrolled_member else None,
            "enrolled_member_id": str(enrolled_member.id) if enrolled_member else None,
        }

    async def add_member(
        self,
        scheme_id: uuid.UUID,
        shop_id: uuid.UUID,
        data: SchemeMemberCreate,
        customer_id: Optional[uuid.UUID] = None,
    ) -> SchemeMemberResponse:
        """Add a member to a scheme."""
        stmt = select(Scheme).options(selectinload(Scheme.members)).where(Scheme.id == scheme_id, Scheme.shop_id == shop_id)
        res = await self.db.execute(stmt)
        scheme = res.scalar_one_or_none()
        if not scheme:
            raise NotFoundException("Scheme not found")

        # Check max members limit
        if scheme.max_members and len(scheme.members) >= scheme.max_members:
            raise BadRequestException(f"This scheme has reached its maximum limit of {scheme.max_members} members.")

        # 1. Normalize phone and build variant lookup list
        phone_clean = normalize_phone_with_country_code(data.customer_phone)
        clean_digits = "".join([c for c in phone_clean if c.isdigit()])
        last10 = clean_digits[-10:] if len(clean_digits) >= 10 else clean_digits
        phone_variants = list(set(filter(None, [
            phone_clean,
            data.customer_phone.strip(),
            clean_digits,
            f"+{clean_digits}" if clean_digits else None,
            f"+91{last10}" if last10 else None,
            f"91{last10}" if last10 else None,
            last10
        ])))

        # 2. Check duplicate by phone variants and last10 in memory
        for m in scheme.members:
            m_phone = (m.customer_phone or "").strip()
            m_digits = "".join(filter(str.isdigit, m_phone))
            m_last10 = m_digits[-10:] if len(m_digits) >= 10 else m_digits
            if m_phone in phone_variants or (last10 and len(last10) >= 10 and m_last10 == last10):
                raise BadRequestException(
                    f"Customer with phone {phone_clean} is already enrolled in this scheme as Member #{m.member_number or 'N/A'} ({m.customer_name}). A customer cannot be added more than once to the same scheme."
                )

        # 3. Resolve or create customer using phone variants and ensure shop membership linkage
        cust = None
        if customer_id:
            cust = await self.db.get(Customer, customer_id)

        if not cust and phone_variants:
            cust_stmt = select(Customer).where(Customer.mobile_number.in_(phone_variants))
            cust_res = await self.db.execute(cust_stmt)
            matched_customers = list(cust_res.scalars().all())
            if matched_customers:
                cust = next((c for c in matched_customers if c.mobile_number == phone_clean), matched_customers[0])

        # 4. Check duplicate by resolved customer_id in memory
        if cust:
            for m in scheme.members:
                if m.customer_id and m.customer_id == cust.id:
                    raise BadRequestException(
                        f"Customer '{cust.name or phone_clean}' is already enrolled in this scheme as Member #{m.member_number or 'N/A'}. A customer cannot be added more than once to the same scheme."
                    )

        # 5. Database-level guarantee query across all members of this scheme
        dup_conditions = [SchemeMember.customer_phone.in_(phone_variants)]
        if cust:
            dup_conditions.append(SchemeMember.customer_id == cust.id)
        if last10 and len(last10) >= 10:
            dup_conditions.append(SchemeMember.customer_phone.like(f"%{last10}"))

        dup_stmt = select(SchemeMember).where(
            SchemeMember.scheme_id == scheme_id,
            or_(*dup_conditions)
        )
        dup_res = await self.db.execute(dup_stmt)
        existing_dup = dup_res.scalars().first()
        if existing_dup:
            raise BadRequestException(
                f"Customer '{existing_dup.customer_name}' ({phone_clean}) is already enrolled in this scheme as Member #{existing_dup.member_number or 'N/A'}. A customer cannot be added more than once to the same scheme."
            )

        trimmed_cust_name = data.customer_name.strip() if data.customer_name else None
        trimmed_cust_address = data.customer_address.strip() if data.customer_address else None

        if cust:
            customer_id = cust.id
            if cust.mobile_number != phone_clean:
                cust_norm = normalize_phone_with_country_code(cust.mobile_number)
                if cust.mobile_number != cust_norm:
                    try:
                        cust.mobile_number = cust_norm
                    except Exception:
                        pass
            if trimmed_cust_name and not cust.name:
                cust.name = trimmed_cust_name
            if trimmed_cust_address and not cust.delivery_address:
                cust.delivery_address = trimmed_cust_address
        else:
            try:
                new_cust = Customer(
                    id=uuid.uuid4(),
                    name=trimmed_cust_name,
                    mobile_number=phone_clean,
                    delivery_address=trimmed_cust_address,
                )
                self.db.add(new_cust)
                await self.db.flush()
                customer_id = new_cust.id
            except Exception as cust_err:
                logger.warning(f"Failed to create new customer for scheme member: {cust_err}")
                cust_stmt = select(Customer).where(Customer.mobile_number.in_(phone_variants))
                cust_res = await self.db.execute(cust_stmt)
                matched_customers = list(cust_res.scalars().all())
                if matched_customers:
                    cust = next((c for c in matched_customers if c.mobile_number == phone_clean), matched_customers[0])
                    customer_id = cust.id
                    if cust.mobile_number != phone_clean:
                        cust_norm = normalize_phone_with_country_code(cust.mobile_number)
                        if cust.mobile_number != cust_norm:
                            try:
                                cust.mobile_number = cust_norm
                            except Exception:
                                pass

        # Crucial: Ensure customer is linked to shop in CustomerRetailerMembership so they appear in /members
        if customer_id:
            try:
                mem_stmt = select(CustomerRetailerMembership).where(
                    CustomerRetailerMembership.customer_id == customer_id,
                    CustomerRetailerMembership.shop_id == shop_id,
                )
                mem_res = await self.db.execute(mem_stmt)
                membership = mem_res.scalar_one_or_none()

                if not membership:
                    new_mem = CustomerRetailerMembership(
                        id=uuid.uuid4(),
                        customer_id=customer_id,
                        shop_id=shop_id,
                        is_retailer_added=False,  # <--- NEW MEMBER category!
                        customer_name=trimmed_cust_name,
                    )
                    self.db.add(new_mem)
                    await self.db.flush()
                else:
                    changed = False
                    if trimmed_cust_name and not membership.customer_name:
                        membership.customer_name = trimmed_cust_name
                        changed = True
                    if changed:
                        await self.db.flush()
            except Exception as mem_err:
                logger.warning(f"Failed to ensure shop membership for scheme member: {mem_err}")

        # Generate member number if not provided
        member_num = data.member_number
        if not member_num or not member_num.strip():
            count = len(scheme.members) + 1
            member_num = f"SCH-{str(count).zfill(3)}"

        now = datetime.now(timezone.utc)
        member = SchemeMember(
            id=uuid.uuid4(),
            scheme_id=scheme.id,
            shop_id=shop_id,
            customer_id=customer_id,
            customer_name=data.customer_name.strip(),
            customer_phone=phone_clean,
            customer_address=data.customer_address.strip() if data.customer_address else None,
            member_number=member_num,
            status="active",
            joined_at=now,
            total_installments=scheme.term_duration,
            paid_installments=0,
            notes=data.notes.strip() if data.notes else None,
        )
        self.db.add(member)

        # Record initial payment if requested
        if data.initial_payment:
            member.paid_installments = 1
            payment = SchemePayment(
                id=uuid.uuid4(),
                scheme_id=scheme.id,
                member_id=member.id,
                shop_id=shop_id,
                installment_number=1,
                installment_label=self._get_installment_label(scheme, 1, now),
                amount=scheme.price,
                status="paid",
                payment_method=data.payment_method or "cash",
                paid_at=now,
                transaction_id=data.transaction_id.strip() if getattr(data, 'transaction_id', None) and data.transaction_id else None,
                notes=data.notes.strip() if data.notes else "Initial installment paid upon enrollment",
            )
            self.db.add(payment)

        # Record permanent activity audit log
        await self._log_activity(
            shop_id=shop_id,
            customer_name=member.customer_name,
            customer_phone=member.customer_phone,
            action_type="ENROLLED",
            scheme_title=scheme.title,
            scheme_id=scheme.id,
            member_id=member.id,
            member_number=member.member_number,
            amount=scheme.price if data.initial_payment else 0,
            installment_number=1 if data.initial_payment else None,
            paid_installments=member.paid_installments,
            total_installments=member.total_installments,
            notes=data.notes or ("Initial installment paid upon enrollment" if data.initial_payment else "Enrolled in scheme"),
        )

        await self.db.commit()

        # Trigger FCM push notification and in-app alert for merchant devices
        try:
            from app.services.notification_service import NotificationService
            notif_service = NotificationService(self.db)
            initial_pay_info = f" (Initial installment: ₹{scheme.price:,.2f} via {data.payment_method or 'cash'})" if data.initial_payment else ""
            await notif_service.create_notification(
                shop_id=shop_id,
                type="NEW_SCHEME_ENROLLMENT",
                title="🪙 New Scheme Enrollment!",
                message=f"{data.customer_name.strip()} ({phone_clean}) enrolled in '{scheme.title}' (Pass: {member_num}){initial_pay_info}.",
                metadata={
                    "scheme_id": str(scheme.id),
                    "member_id": str(member.id),
                    "customer_name": data.customer_name.strip(),
                    "customer_phone": phone_clean,
                    "member_number": member_num,
                    "target_url": "/schemes",
                }
            )
        except Exception as notif_err:
            import logging
            logging.getLogger(__name__).error(f"Failed to create scheme enrollment notification: {notif_err}", exc_info=True)

        # Trigger background email notification to store owner and admin
        try:
            asyncio.create_task(
                self._send_scheme_enrollment_email(
                    shop_id=shop_id,
                    scheme=scheme,
                    member=member,
                    payment_method=data.payment_method or "cash",
                )
            )
        except Exception as email_err:
            import logging
            logging.getLogger(__name__).error(f"Failed to schedule scheme enrollment email: {email_err}", exc_info=True)

        # Re-fetch with payments loaded
        fetch_stmt = (
            select(SchemeMember)
            .options(selectinload(SchemeMember.payments))
            .where(SchemeMember.id == member.id)
        )
        fetch_res = await self.db.execute(fetch_stmt)
        refreshed = fetch_res.scalar_one()
        return self._format_member_response(refreshed, scheme)

    async def record_payment(
        self,
        scheme_id: uuid.UUID,
        shop_id: uuid.UUID,
        member_id: uuid.UUID,
        data: RecordPaymentRequest,
    ) -> SchemeMemberResponse:
        """Record an installment payment for a member."""
        scheme_stmt = select(Scheme).where(Scheme.id == scheme_id, Scheme.shop_id == shop_id)
        scheme_res = await self.db.execute(scheme_stmt)
        scheme = scheme_res.scalar_one_or_none()
        if not scheme:
            raise NotFoundException("Scheme not found")

        member_stmt = (
            select(SchemeMember)
            .options(selectinload(SchemeMember.payments))
            .where(SchemeMember.id == member_id, SchemeMember.scheme_id == scheme_id)
        )
        member_res = await self.db.execute(member_stmt)
        member = member_res.scalar_one_or_none()
        if not member:
            raise NotFoundException("Member not found in this scheme")

        # Strict sequential allocation: assign the next consecutive installment
        existing_paid = {p.installment_number for p in member.payments if p.status == "paid"}
        next_num = 1
        while next_num in existing_paid:
            next_num += 1

        if next_num > member.total_installments:
            raise BadRequestException("All installments for this scheme have already been paid.")

        target_installment_number = next_num
        now = datetime.now(timezone.utc)
        label = self._get_installment_label(scheme, target_installment_number, member.joined_at)
        amount = data.amount if data.amount is not None else scheme.price

        payment = SchemePayment(
            id=uuid.uuid4(),
            scheme_id=scheme.id,
            member_id=member.id,
            shop_id=shop_id,
            installment_number=target_installment_number,
            installment_label=label,
            amount=amount,
            status="paid",
            payment_method=data.payment_method,
            paid_at=now,
            transaction_id=data.transaction_id,
            notes=data.notes,
        )
        self.db.add(payment)

        # Update member paid installments count
        member.paid_installments = len(existing_paid) + 1
        if member.paid_installments >= member.total_installments:
            member.status = "completed"

        # Ensure member phone and customer mobile number include country code
        norm_member_phone = normalize_phone_with_country_code(member.customer_phone)
        if member.customer_phone != norm_member_phone:
            member.customer_phone = norm_member_phone
        if member.customer_id:
            cust = await self.db.get(Customer, member.customer_id)
            if cust and cust.mobile_number:
                cust_norm = normalize_phone_with_country_code(cust.mobile_number)
                if cust.mobile_number != cust_norm:
                    try:
                        cust.mobile_number = cust_norm
                    except Exception:
                        pass

        # Record permanent activity audit log
        await self._log_activity(
            shop_id=shop_id,
            customer_name=member.customer_name,
            customer_phone=member.customer_phone,
            action_type="PAYMENT_RECORDED",
            scheme_title=scheme.title,
            scheme_id=scheme.id,
            member_id=member.id,
            member_number=member.member_number,
            amount=amount,
            installment_number=target_installment_number,
            paid_installments=member.paid_installments,
            total_installments=member.total_installments,
            notes=f"Paid via {data.payment_method.upper()}" + (f" - Ref: {data.transaction_id}" if data.transaction_id else ""),
        )

        await self.db.commit()

        # Re-fetch refreshed member
        refreshed_res = await self.db.execute(member_stmt)
        refreshed = refreshed_res.scalar_one()
        return self._format_member_response(refreshed, scheme)

    async def send_member_delete_otp(
        self, scheme_id: uuid.UUID, shop_id: uuid.UUID, member_id: uuid.UUID
    ) -> SchemeMemberDeleteOtpResponse:
        """Trigger SMS OTP to customer for cancelling / deleting an enrolled scheme membership."""
        stmt = (
            select(SchemeMember)
            .options(selectinload(SchemeMember.payments), selectinload(SchemeMember.scheme))
            .where(
                SchemeMember.id == member_id,
                SchemeMember.scheme_id == scheme_id,
                SchemeMember.shop_id == shop_id,
            )
        )
        res = await self.db.execute(stmt)
        member = res.scalar_one_or_none()
        if not member:
            raise NotFoundException("Scheme member not found")

        scheme = member.scheme
        total_paid = sum(float(p.amount) for p in member.payments if p.status == "paid")

        from app.services.sms_service import SMSService
        sms_service = SMSService()

        req_id = await sms_service.send_otp(
            mobile_number=member.customer_phone,
            country_code="91",
        )

        phone_clean = member.customer_phone.strip()
        last4 = phone_clean[-4:] if len(phone_clean) >= 4 else phone_clean
        masked = f"+91 ******{last4}"

        return SchemeMemberDeleteOtpResponse(
            success=True,
            verification_id=req_id,
            customer_phone_masked=masked,
            paid_installments=member.paid_installments,
            total_paid_amount=total_paid,
            message=f"OTP sent to {masked} to authorize scheme enrollment cancellation."
        )

    async def delete_member(
        self,
        scheme_id: uuid.UUID,
        shop_id: uuid.UUID,
        member_id: uuid.UUID,
        otp: Optional[str] = None,
        verification_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> bool:
        """Delete an enrolled member. Requires customer OTP verification if payments exist."""
        stmt = (
            select(SchemeMember)
            .options(selectinload(SchemeMember.payments), selectinload(SchemeMember.scheme))
            .where(
                SchemeMember.id == member_id,
                SchemeMember.scheme_id == scheme_id,
                SchemeMember.shop_id == shop_id,
            )
        )
        res = await self.db.execute(stmt)
        member = res.scalar_one_or_none()
        if not member:
            raise NotFoundException("Scheme member not found")

        if not reason or not reason.strip():
            raise BadRequestException("Reason / settlement notes are required to delete a member.")

        scheme = member.scheme
        total_paid = sum(float(p.amount) for p in member.payments if p.status == "paid")

        # Anti-fraud check: If payments or installments were recorded, customer OTP is strictly mandatory!
        if member.paid_installments > 0 or len(member.payments) > 0 or total_paid > 0:
            if not verification_id or not str(verification_id).strip():
                raise BadRequestException(
                    "Customer OTP has not been requested yet. Please click 'Send OTP to Customer Phone' first."
                )
            if not otp or not str(otp).strip():
                raise BadRequestException(
                    "Customer OTP verification is strictly required to delete this enrollment because payments have been recorded."
                )
            clean_otp = str(otp).strip()
            if len(clean_otp) != 6 or not clean_otp.isdigit():
                raise BadRequestException("Please enter a valid 6-digit customer OTP.")

            from app.services.sms_service import SMSService
            sms_service = SMSService()
            is_valid = await sms_service.verify_otp(
                verification_id=verification_id.strip(),
                code=clean_otp,
                mobile_number=member.customer_phone,
            )
            if not is_valid:
                raise BadRequestException("Invalid or expired customer OTP. Cancellation request denied.")

        # Log notification / audit alert for store owner
        try:
            from app.services.notification_service import NotificationService
            notif_service = NotificationService(self.db)
            await notif_service.create_notification(
                shop_id=shop_id,
                type="SCHEME_MEMBER_DELETED",
                title="⚠️ Scheme Member Removed",
                message=(
                    f"Member '{member.customer_name}' ({member.customer_phone}) was removed from '{scheme.title}'. "
                    f"Settled payments: {member.paid_installments} installments (₹{total_paid:,.2f}). "
                    f"Reason: {reason or 'Customer verified with OTP'}"
                ),
                metadata={
                    "scheme_id": str(scheme.id),
                    "member_id": str(member.id),
                    "customer_name": member.customer_name,
                    "customer_phone": member.customer_phone,
                    "paid_installments": member.paid_installments,
                    "total_paid": total_paid,
                    "reason": reason,
                }
            )
        except Exception as notif_err:
            logger.error(f"Failed to record scheme member deletion notification: {notif_err}")

        # Record permanent activity audit log (persists even after member is deleted)
        await self._log_activity(
            shop_id=shop_id,
            customer_name=member.customer_name,
            customer_phone=member.customer_phone,
            action_type="DELETED",
            scheme_title=scheme.title,
            scheme_id=scheme.id,
            member_id=member.id,
            member_number=member.member_number,
            amount=total_paid,
            paid_installments=member.paid_installments,
            total_installments=member.total_installments,
            otp_verified=True if (member.paid_installments > 0 or total_paid > 0) else False,
            notes=reason or ("Accidental enrollment removed" if member.paid_installments == 0 else "Cancelled with customer OTP"),
        )

        # Delete member (cascade will delete associated payments)
        await self.db.delete(member)
        await self.db.commit()
        return True

    async def transfer_member(
        self,
        current_scheme_id: uuid.UUID,
        shop_id: uuid.UUID,
        member_id: uuid.UUID,
        target_scheme_id: uuid.UUID,
        notes: str = "",
    ) -> SchemeMemberResponse:
        """Transfer an enrolled member to another scheme within the same shop."""
        if not notes or not notes.strip():
            raise BadRequestException("Transfer notes / reason is required.")
        if current_scheme_id == target_scheme_id:
            raise BadRequestException("Target scheme must be different from current scheme.")

        # Fetch member with current scheme
        stmt = (
            select(SchemeMember)
            .options(selectinload(SchemeMember.payments), selectinload(SchemeMember.scheme))
            .where(
                SchemeMember.id == member_id,
                SchemeMember.scheme_id == current_scheme_id,
                SchemeMember.shop_id == shop_id,
            )
        )
        res = await self.db.execute(stmt)
        member = res.scalar_one_or_none()
        if not member:
            raise NotFoundException("Scheme member not found")

        prev_scheme_title = member.scheme.title if getattr(member, 'scheme', None) else "Previous Scheme"
        prev_scheme_price = float(member.scheme.price) if getattr(member, 'scheme', None) else 0.0

        # Fetch target scheme
        target_stmt = (
            select(Scheme)
            .options(selectinload(Scheme.members))
            .where(Scheme.id == target_scheme_id, Scheme.shop_id == shop_id)
        )
        target_res = await self.db.execute(target_stmt)
        target_scheme = target_res.scalar_one_or_none()
        if not target_scheme:
            raise NotFoundException("Target scheme not found")

        if target_scheme.status != "active":
            raise BadRequestException(f"Target scheme '{target_scheme.title}' is not active.")

        if target_scheme.max_members and len(target_scheme.members) >= target_scheme.max_members:
            raise BadRequestException(f"Target scheme has reached its limit of {target_scheme.max_members} members.")

        phone_clean = normalize_phone_with_country_code(member.customer_phone)
        last10 = "".join(filter(str.isdigit, phone_clean))[-10:]
        if any(
            (m.customer_phone.strip() == phone_clean or "".join(filter(str.isdigit, m.customer_phone))[-10:] == last10)
            and m.id != member.id
            for m in target_scheme.members
        ):
            raise BadRequestException(f"Customer phone {phone_clean} is already enrolled in '{target_scheme.title}'.")

        diff_amount = (float(target_scheme.price) - prev_scheme_price) * member.paid_installments

        # Update member fields
        member.scheme_id = target_scheme.id
        member.total_installments = target_scheme.term_duration
        if notes:
            member.notes = f"{member.notes + ' | ' if member.notes else ''}{notes.strip()}"

        # Transfer existing payments to new scheme_id
        for p in member.payments:
            p.scheme_id = target_scheme.id

        # Record permanent activity audit log
        await self._log_activity(
            shop_id=shop_id,
            customer_name=member.customer_name,
            customer_phone=member.customer_phone,
            action_type="TRANSFERRED",
            scheme_title=target_scheme.title,
            scheme_id=target_scheme.id,
            member_id=member.id,
            member_number=member.member_number,
            from_scheme_title=prev_scheme_title,
            to_scheme_title=target_scheme.title,
            amount=diff_amount,
            paid_installments=member.paid_installments,
            total_installments=target_scheme.term_duration,
            notes=notes or f"Transferred from '{prev_scheme_title}' to '{target_scheme.title}'",
        )

        await self.db.commit()

        # Re-fetch refreshed member
        refetch_stmt = (
            select(SchemeMember)
            .options(selectinload(SchemeMember.payments))
            .where(SchemeMember.id == member.id)
        )
        refetch_res = await self.db.execute(refetch_stmt)
        refreshed = refetch_res.scalar_one()
        return self._format_member_response(refreshed, target_scheme)

    async def get_customer_history(self, shop_id: uuid.UUID, phone: str) -> List[SchemeActivityLogResponse]:
        """Fetch permanent activity timeline for a customer by mobile phone."""
        clean_phone = phone.strip()
        norm_phone = normalize_phone_with_country_code(phone)
        digits_only = re.sub(r'\D', '', clean_phone)
        last_10 = digits_only[-10:] if len(digits_only) >= 10 else digits_only

        conditions = [SchemeActivityLog.customer_phone == clean_phone]
        if norm_phone and norm_phone != clean_phone:
            conditions.append(SchemeActivityLog.customer_phone == norm_phone)
        if digits_only and digits_only != clean_phone:
            conditions.append(SchemeActivityLog.customer_phone == digits_only)
        if len(last_10) >= 7:
            conditions.append(SchemeActivityLog.customer_phone.endswith(last_10))

        stmt = (
            select(SchemeActivityLog)
            .where(
                SchemeActivityLog.shop_id == shop_id,
                or_(*conditions)
            )
            .order_by(SchemeActivityLog.created_at.desc())
        )
        res = await self.db.execute(stmt)
        logs = list(res.scalars().all())

        return [
            SchemeActivityLogResponse(
                id=str(l.id),
                shop_id=str(l.shop_id),
                scheme_id=str(l.scheme_id) if l.scheme_id else None,
                member_id=str(l.member_id) if l.member_id else None,
                customer_name=l.customer_name,
                customer_phone=normalize_phone_with_country_code(l.customer_phone),
                member_number=l.member_number,
                action_type=l.action_type,
                scheme_title=l.scheme_title,
                from_scheme_title=l.from_scheme_title,
                to_scheme_title=l.to_scheme_title,
                amount=float(l.amount) if l.amount is not None else None,
                installment_number=l.installment_number,
                paid_installments=l.paid_installments,
                total_installments=l.total_installments,
                otp_verified=l.otp_verified,
                notes=l.notes,
                created_at=l.created_at,
            )
            for l in logs
        ]



    # ------------------ Public Methods ------------------

    async def get_public_schemes(self, shop_id: uuid.UUID) -> List[PublicSchemeResponse]:
        """Get active public schemes for customers on the public menu."""
        # Check if savings schemes are enabled in shop settings
        st_res = await self.db.execute(select(ShopSettings).where(ShopSettings.shop_id == shop_id))
        shop_settings = st_res.scalar_one_or_none()
        if shop_settings and not shop_settings.savings_schemes_enabled:
            return []

        stmt = (
            select(Scheme)
            .options(selectinload(Scheme.members))
            .where(Scheme.shop_id == shop_id, Scheme.show_on_public_menu == True, Scheme.status == "active")
            .order_by(Scheme.created_at.desc())
        )
        res = await self.db.execute(stmt)
        schemes = list(res.scalars().all())

        results = []
        for s in schemes:
            total_m = len(s.members)
            remaining_spots = (s.max_members - total_m) if s.max_members is not None else None
            results.append(
                PublicSchemeResponse(
                    id=str(s.id),
                    shop_id=str(s.shop_id),
                    title=s.title,
                    description=s.description,
                    image_url=getattr(s, "image_url", None),
                    price=float(s.price),
                    frequency=s.frequency,
                    term_duration=s.term_duration,
                    term_unit=s.term_unit,
                    max_members=s.max_members,
                    total_members=total_m,
                    remaining_spots=remaining_spots,
                    items=s.items or [],
                    status=s.status,
                    reward_type=getattr(s, "reward_type", "specific_items") or "specific_items",
                    reward_categories=getattr(s, "reward_categories", []) or [],
                    highlight_text=getattr(s, "highlight_text", None),
                )
            )
        return results

    async def public_join_scheme(
        self, scheme_id: uuid.UUID, shop_id: uuid.UUID, data: SchemeMemberCreate, customer_id: Optional[uuid.UUID] = None
    ) -> SchemeMemberResponse:
        """Public endpoint allowing a customer to join a scheme."""
        st_res = await self.db.execute(select(ShopSettings).where(ShopSettings.shop_id == shop_id))
        shop_settings = st_res.scalar_one_or_none()
        if shop_settings and not shop_settings.savings_schemes_enabled:
            raise BadRequestException("Savings schemes are currently disabled for this shop.")

        return await self.add_member(scheme_id, shop_id, data, customer_id)

    async def initiate_join_payment(
        self, scheme_id: uuid.UUID, shop_id: uuid.UUID, data: SchemePaymentInitiateRequest
    ) -> SchemePaymentInitiateResponse:
        """Initiate Razorpay order for enrolling in a scheme with 2% platform commission and 3% (+18% GST) PG fee."""
        st_res = await self.db.execute(select(ShopSettings).where(ShopSettings.shop_id == shop_id))
        shop_settings = st_res.scalar_one_or_none()
        if shop_settings and not shop_settings.savings_schemes_enabled:
            raise BadRequestException("Savings schemes are currently disabled for this shop.")

        settings = get_settings()

        # 1. Fetch scheme
        scheme_stmt = (
            select(Scheme)
            .options(selectinload(Scheme.members))
            .where(Scheme.id == scheme_id, Scheme.shop_id == shop_id)
        )
        scheme_res = await self.db.execute(scheme_stmt)
        scheme = scheme_res.scalar_one_or_none()
        if not scheme:
            raise NotFoundException("Scheme not found")

        if scheme.status != "active":
            raise BadRequestException("This scheme is no longer accepting new enrollments.")

        if scheme.max_members and len(scheme.members) >= scheme.max_members:
            raise BadRequestException(f"This scheme has reached its maximum limit of {scheme.max_members} members.")

        phone_clean = normalize_phone_with_country_code(data.customer_phone)
        clean_digits = "".join([c for c in phone_clean if c.isdigit()])
        last10 = clean_digits[-10:] if len(clean_digits) >= 10 else clean_digits
        phone_variants = list(set(filter(None, [
            phone_clean,
            data.customer_phone.strip(),
            clean_digits,
            f"+{clean_digits}" if clean_digits else None,
            f"+91{last10}" if last10 else None,
            f"91{last10}" if last10 else None,
            last10
        ])))

        for m in scheme.members:
            m_phone = (m.customer_phone or "").strip()
            m_digits = "".join(filter(str.isdigit, m_phone))
            m_last10 = m_digits[-10:] if len(m_digits) >= 10 else m_digits
            if m_phone in phone_variants or (last10 and len(last10) >= 10 and m_last10 == last10):
                raise BadRequestException(
                    f"A member with phone {phone_clean} is already enrolled in this scheme as Member #{m.member_number or 'N/A'} ({m.customer_name})."
                )

        dup_conditions = [SchemeMember.customer_phone.in_(phone_variants)]
        if last10 and len(last10) >= 10:
            dup_conditions.append(SchemeMember.customer_phone.like(f"%{last10}"))

        dup_stmt = select(SchemeMember).where(
            SchemeMember.scheme_id == scheme_id,
            or_(*dup_conditions)
        )
        dup_res = await self.db.execute(dup_stmt)
        existing_dup = dup_res.scalars().first()
        if existing_dup:
            raise BadRequestException(
                f"Customer '{existing_dup.customer_name}' ({phone_clean}) is already enrolled in this scheme as Member #{existing_dup.member_number or 'N/A'}."
            )

        # 2. Calculate centralized order pricing
        pricing = calculate_order_pricing(float(scheme.price), is_online=True)
        base_total = float(scheme.price)
        platform_fee = pricing.platform_fee
        pg_fee = pricing.gateway_fee
        gst_on_fee = pricing.gateway_gst
        grand_total = pricing.total_payable
        amount_subunits = pricing.amount_subunits

        # 3. Handle mock mode
        if settings.MOCK_PAYMENT_MODE:
            mock_order_id = f"sch_mock_{uuid.uuid4().hex[:12]}"
            return SchemePaymentInitiateResponse(
                razorpay_order_id=mock_order_id,
                razorpay_key=settings.RAZORPAY_KEY_ID or "rzp_test_mock",
                base_total=base_total,
                platform_fee=platform_fee,
                pg_fee=pg_fee,
                gst_on_fee=gst_on_fee,
                grand_total=grand_total,
                amount=amount_subunits,
                currency="INR",
                mock_mode=True,
            )

        # 4. Create real Razorpay order with Route vendor split
        import razorpay
        client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

        # Check vendor shop settings for Razorpay Route Account
        shop_stmt = select(Shop).options(selectinload(Shop.settings)).where(Shop.id == shop_id)
        shop_res = await self.db.execute(shop_stmt)
        shop = shop_res.scalar_one_or_none()
        shop_settings = shop.settings if shop else None

        order_data: Dict[str, Any] = {
            "amount": amount_subunits,
            "currency": "INR",
            "receipt": f"sch_{str(scheme_id)[:8]}_{int(datetime.now(timezone.utc).timestamp())}",
            "notes": {
                "scheme_id": str(scheme_id),
                "shop_id": str(shop_id),
                "customer_name": data.customer_name,
                "customer_phone": phone_clean,
                "base_price": str(base_total),
                "platform_fee": str(platform_fee),
                "pg_fee": str(pg_fee),
                "gst_on_fee": str(gst_on_fee),
                "grand_total": str(grand_total),
            },
        }

        # If vendor has a linked Razorpay account, route 100% of vendor base amount to their account
        # Platform fee (2%), PG fee (3%), and 18% GST remain in the platform account
        if shop_settings and shop_settings.razorpay_account_id:
            vendor_amount_subunits = int(round(base_total * 100))
            order_data["transfers"] = [
                {
                    "account": shop_settings.razorpay_account_id,
                    "amount": vendor_amount_subunits,
                    "currency": "INR",
                    "notes": {
                        "type": "vendor_payout",
                        "scheme_id": str(scheme_id),
                        "shop_id": str(shop_id),
                    },
                    "on_hold": 0,
                }
            ]

        try:
            rzp_order = client.order.create(data=order_data)
        except Exception as rzp_e:
            print(f"DEBUG: Scheme Razorpay order creation with transfers failed: {rzp_e}")
            if "transfers" in order_data:
                print("DEBUG: Retrying order creation WITHOUT transfers array. Platform owner will settle manually.")
                del order_data["transfers"]
                rzp_order = client.order.create(data=order_data)
            else:
                raise BadRequestException(f"Payment gateway error: {str(rzp_e)}")

        return SchemePaymentInitiateResponse(
            razorpay_order_id=rzp_order["id"],
            razorpay_key=settings.RAZORPAY_KEY_ID,
            base_total=base_total,
            platform_fee=platform_fee,
            pg_fee=pg_fee,
            gst_on_fee=gst_on_fee,
            grand_total=grand_total,
            amount=rzp_order["amount"],
            currency=rzp_order.get("currency", "INR"),
            mock_mode=False,
        )

    async def verify_join_payment(
        self, scheme_id: uuid.UUID, shop_id: uuid.UUID, data: SchemePaymentVerifyRequest
    ) -> SchemeMemberResponse:
        """Verify Razorpay payment signature and complete enrollment with 1st installment paid."""
        settings = get_settings()

        # Check signature unless mock mode
        if not settings.MOCK_PAYMENT_MODE and not data.razorpay_order_id.startswith("sch_mock_"):
            generated_signature = hmac.new(
                settings.RAZORPAY_KEY_SECRET.encode(),
                f"{data.razorpay_order_id}|{data.razorpay_payment_id}".encode(),
                hashlib.sha256,
            ).hexdigest()
            if generated_signature != data.razorpay_signature:
                raise BadRequestException("Invalid payment signature from Razorpay.")

        # Create member with initial installment paid
        member_payload = SchemeMemberCreate(
            customer_name=data.customer_name.strip(),
            customer_phone=normalize_phone_with_country_code(data.customer_phone),
            customer_address=data.customer_address.strip() if data.customer_address else None,
            initial_payment=True,
            payment_method="razorpay",
            transaction_id=data.razorpay_payment_id,
            notes=f"Paid via Razorpay (Order: {data.razorpay_order_id}, Payment: {data.razorpay_payment_id})",
        )
        return await self.public_join_scheme(scheme_id, shop_id, member_payload)

    async def get_customer_scheme_passes(self, shop_id: uuid.UUID, phone: str) -> List[CustomerSchemePassResponse]:
        """Retrieve customer's active scheme passes and progress by mobile phone."""
        clean_phone = phone.strip()
        norm_phone = normalize_phone_with_country_code(phone)
        digits_only = re.sub(r'\D', '', clean_phone)
        last_10 = digits_only[-10:] if len(digits_only) >= 10 else digits_only

        conditions = [SchemeMember.customer_phone == clean_phone]
        if norm_phone and norm_phone != clean_phone:
            conditions.append(SchemeMember.customer_phone == norm_phone)
        if digits_only and digits_only != clean_phone:
            conditions.append(SchemeMember.customer_phone == digits_only)
        if len(last_10) >= 7:
            conditions.append(SchemeMember.customer_phone.endswith(last_10))

        stmt = (
            select(SchemeMember)
            .options(selectinload(SchemeMember.payments), selectinload(SchemeMember.scheme))
            .where(
                SchemeMember.shop_id == shop_id,
                or_(*conditions)
            )
            .order_by(SchemeMember.joined_at.desc())
        )
        res = await self.db.execute(stmt)
        members = list(res.scalars().all())

        passes = []
        for m in members:
            scheme = m.scheme
            if not scheme:
                continue
            schedule = self._build_installment_schedule(m, scheme)
            remaining = max(0, m.total_installments - m.paid_installments)
            passes.append(
                CustomerSchemePassResponse(
                    member_id=str(m.id),
                    scheme_id=str(scheme.id),
                    scheme_title=scheme.title,
                    image_url=getattr(scheme, "image_url", None),
                    price=float(scheme.price),
                    frequency=scheme.frequency,
                    term_duration=scheme.term_duration,
                    term_unit=scheme.term_unit,
                    customer_name=m.customer_name,
                    customer_phone=normalize_phone_with_country_code(m.customer_phone),
                    member_number=m.member_number,
                    status=m.status,
                    joined_at=m.joined_at,
                    total_installments=m.total_installments,
                    paid_installments=m.paid_installments,
                    remaining_installments=remaining,
                    items=scheme.items or [],
                    reward_type=getattr(scheme, "reward_type", "specific_items") or "specific_items",
                    reward_categories=getattr(scheme, "reward_categories", []) or [],
                    highlight_text=getattr(scheme, "highlight_text", None),
                    payments=[
                        SchemePaymentResponse(
                            id=str(p.id),
                            scheme_id=str(p.scheme_id),
                            member_id=str(p.member_id),
                            installment_number=p.installment_number,
                            installment_label=p.installment_label,
                            amount=float(p.amount),
                            status=p.status,
                            payment_method=p.payment_method,
                            paid_at=p.paid_at,
                            transaction_id=p.transaction_id,
                            notes=p.notes,
                        )
                        for p in m.payments
                    ],
                    installment_schedule=schedule,
                )
            )
        return passes

    async def initiate_installment_payment(
        self, scheme_id: uuid.UUID, shop_id: uuid.UUID, member_id: uuid.UUID
    ) -> SchemePaymentInitiateResponse:
        """Initiate Razorpay order for an enrolled member's next due installment."""
        settings = get_settings()

        scheme_stmt = select(Scheme).where(Scheme.id == scheme_id, Scheme.shop_id == shop_id)
        scheme_res = await self.db.execute(scheme_stmt)
        scheme = scheme_res.scalar_one_or_none()
        if not scheme:
            raise NotFoundException("Scheme not found")

        if scheme.status == "completed" or scheme.status == "closed":
            raise BadRequestException("This scheme has expired or closed. Further installment payments cannot be accepted.")

        member_stmt = (
            select(SchemeMember)
            .options(selectinload(SchemeMember.payments))
            .where(SchemeMember.id == member_id, SchemeMember.scheme_id == scheme_id)
        )
        member_res = await self.db.execute(member_stmt)
        member = member_res.scalar_one_or_none()
        if not member:
            raise NotFoundException("Member not found in this scheme")

        if member.status == "completed" or member.paid_installments >= member.total_installments:
            raise BadRequestException("All installments for this scheme pass have already been completed!")

        # Next due installment is strictly the next unpaid installment
        next_num = member.paid_installments + 1

        # Centralized pricing (2% platform commission, 3% PG fee, 18% GST)
        pricing = calculate_order_pricing(float(scheme.price), is_online=True)
        base_total = float(scheme.price)
        platform_fee = pricing.platform_fee
        pg_fee = pricing.gateway_fee
        gst_on_fee = pricing.gateway_gst
        grand_total = pricing.total_payable
        amount_subunits = pricing.amount_subunits

        # Mock mode
        if settings.MOCK_PAYMENT_MODE:
            mock_order_id = f"inst_mock_{uuid.uuid4().hex[:12]}"
            return SchemePaymentInitiateResponse(
                razorpay_order_id=mock_order_id,
                razorpay_key=settings.RAZORPAY_KEY_ID or "rzp_test_mock",
                base_total=base_total,
                platform_fee=platform_fee,
                pg_fee=pg_fee,
                gst_on_fee=gst_on_fee,
                grand_total=grand_total,
                amount=amount_subunits,
                currency="INR",
                mock_mode=True,
            )

        import razorpay
        client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

        shop_stmt = select(Shop).options(selectinload(Shop.settings)).where(Shop.id == shop_id)
        shop_res = await self.db.execute(shop_stmt)
        shop = shop_res.scalar_one_or_none()
        shop_settings = shop.settings if shop else None

        order_data: Dict[str, Any] = {
            "amount": amount_subunits,
            "currency": "INR",
            "receipt": f"inst_{str(member_id)[:6]}_{next_num}_{int(datetime.now(timezone.utc).timestamp())}",
            "notes": {
                "scheme_id": str(scheme_id),
                "shop_id": str(shop_id),
                "member_id": str(member_id),
                "installment_number": str(next_num),
                "customer_name": member.customer_name,
                "customer_phone": member.customer_phone,
                "base_price": str(base_total),
                "platform_fee": str(platform_fee),
                "pg_fee": str(pg_fee),
                "gst_on_fee": str(gst_on_fee),
                "grand_total": str(grand_total),
            },
        }

        # Route vendor payout
        if shop_settings and shop_settings.razorpay_account_id:
            vendor_amount_subunits = int(round(base_total * 100))
            order_data["transfers"] = [
                {
                    "account": shop_settings.razorpay_account_id,
                    "amount": vendor_amount_subunits,
                    "currency": "INR",
                    "notes": {
                        "type": "vendor_payout",
                        "scheme_id": str(scheme_id),
                        "member_id": str(member_id),
                        "installment": str(next_num),
                    },
                    "on_hold": 0,
                }
            ]

        try:
            rzp_order = client.order.create(data=order_data)
        except Exception as rzp_e:
            print(f"DEBUG: Razorpay installment order creation failed: {rzp_e}")
            if "transfers" in order_data:
                del order_data["transfers"]
                rzp_order = client.order.create(data=order_data)
            else:
                raise BadRequestException(f"Payment gateway error: {str(rzp_e)}")

        return SchemePaymentInitiateResponse(
            razorpay_order_id=rzp_order["id"],
            razorpay_key=settings.RAZORPAY_KEY_ID,
            base_total=base_total,
            platform_fee=platform_fee,
            pg_fee=pg_fee,
            gst_on_fee=gst_on_fee,
            grand_total=grand_total,
            amount=rzp_order["amount"],
            currency=rzp_order.get("currency", "INR"),
            mock_mode=False,
        )

    async def verify_installment_payment(
        self, scheme_id: uuid.UUID, shop_id: uuid.UUID, member_id: uuid.UUID, data: SchemePaymentVerifyRequest
    ) -> CustomerSchemePassResponse:
        """Verify signature and record installment payment."""
        settings = get_settings()

        if not settings.MOCK_PAYMENT_MODE and not data.razorpay_order_id.startswith("inst_mock_"):
            generated_signature = hmac.new(
                settings.RAZORPAY_KEY_SECRET.encode(),
                f"{data.razorpay_order_id}|{data.razorpay_payment_id}".encode(),
                hashlib.sha256,
            ).hexdigest()
            if generated_signature != data.razorpay_signature:
                raise BadRequestException("Invalid payment signature from Razorpay.")

        scheme_stmt = select(Scheme).where(Scheme.id == scheme_id, Scheme.shop_id == shop_id)
        scheme_res = await self.db.execute(scheme_stmt)
        scheme = scheme_res.scalar_one_or_none()
        if not scheme:
            raise NotFoundException("Scheme not found")

        member_stmt = (
            select(SchemeMember)
            .options(selectinload(SchemeMember.payments))
            .where(SchemeMember.id == member_id, SchemeMember.scheme_id == scheme_id)
        )
        member_res = await self.db.execute(member_stmt)
        member = member_res.scalar_one_or_none()
        if not member:
            raise NotFoundException("Member not found")

        existing_paid = {p.installment_number for p in member.payments if p.status == "paid"}
        next_num = len(existing_paid) + 1
        now = datetime.now(timezone.utc)
        label = self._get_installment_label(scheme, next_num, member.joined_at)

        payment = SchemePayment(
            id=uuid.uuid4(),
            scheme_id=scheme.id,
            member_id=member.id,
            shop_id=shop_id,
            installment_number=next_num,
            installment_label=label,
            amount=scheme.price,
            status="paid",
            payment_method="razorpay",
            paid_at=now,
            transaction_id=data.razorpay_payment_id,
            notes=f"Paid online via Razorpay (Order: {data.razorpay_order_id})",
        )
        self.db.add(payment)
        member.paid_installments = len(existing_paid) + 1
        if member.paid_installments >= member.total_installments:
            member.status = "completed"

        await self.db.commit()

        # Re-fetch customer passes
        passes = await self.get_customer_scheme_passes(shop_id, member.customer_phone)
        for p in passes:
            if p.member_id == str(member.id):
                return p
        return passes[0]

    # ------------------ Helper Calculations ------------------

    def _calculate_scheme_stats(self, scheme: Scheme) -> SchemeStats:
        """Calculates members, paid count for this cycle (month/week), and total revenue."""
        members = scheme.members or []
        payments = scheme.payments or []
        total_m = len(members)

        total_collected = sum(float(p.amount) for p in payments if p.status == "paid")

        # Determine current cycle index (e.g. Month 1, Month 2, etc.) based on scheme start_date
        now = datetime.now(timezone.utc)
        cycle_idx = self._get_current_cycle_index(scheme, now)

        # Count how many members have paid for the current cycle using preloaded payments and paid_installments
        paid_member_ids = {
            p.member_id for p in payments
            if p.status == "paid" and p.installment_number == cycle_idx
        }
        paid_this_cycle = sum(
            1 for m in members
            if m.paid_installments >= cycle_idx or m.id in paid_member_ids
        )

        pending_this_cycle = max(0, total_m - paid_this_cycle)
        completion_rate = (
            round((sum(m.paid_installments for m in members) / (total_m * scheme.term_duration)) * 100, 1)
            if total_m > 0 and scheme.term_duration > 0
            else 0.0
        )

        return SchemeStats(
            total_members=total_m,
            paid_this_cycle_count=paid_this_cycle,
            pending_this_cycle_count=pending_this_cycle,
            total_collected=round(total_collected, 2),
            completion_rate_percent=completion_rate,
        )

    def _get_current_cycle_index(self, scheme: Scheme, current_time: datetime) -> int:
        """Determines the current installment cycle number (1..N)."""
        base_time = scheme.start_date or scheme.created_at
        if not base_time:
            return 1
        delta = current_time - base_time
        days = max(0, delta.days)

        if scheme.frequency == "weekly":
            cycle = (days // 7) + 1
        else:
            # Approx 30 days per month
            cycle = (days // 30) + 1

        return min(max(1, cycle), scheme.term_duration)

    def _get_installment_label(self, scheme: Scheme, installment_num: int, start_time: datetime) -> str:
        """Generates friendly label: e.g. 'Month 1 (Nov 2026)' or 'Week 3'."""
        if scheme.frequency == "weekly":
            return f"Week {installment_num}"

        # Monthly: calculate month name
        approx_date = start_time + timedelta(days=30 * (installment_num - 1))
        month_name = approx_date.strftime("%b %Y")
        return f"Month {installment_num} ({month_name})"

    def _build_installment_schedule(self, member: SchemeMember, scheme: Scheme) -> List[InstallmentScheduleItem]:
        """Constructs list of all installments with payment status for a member."""
        # Chronologically sort paid payments and map them consecutively to installment numbers 1..N
        paid_payments = sorted(
            [p for p in (member.payments or []) if p.status == "paid"],
            key=lambda p: (p.installment_number, p.paid_at or p.created_at)
        )
        payments_by_num = {}
        for idx, p in enumerate(paid_payments, start=1):
            payments_by_num[idx] = p
        items = []

        for num in range(1, member.total_installments + 1):
            payment = payments_by_num.get(num)
            label = self._get_installment_label(scheme, num, member.joined_at)
            due_date = member.joined_at + (
                timedelta(weeks=num - 1) if scheme.frequency == "weekly" else timedelta(days=30 * (num - 1))
            )

            items.append(
                InstallmentScheduleItem(
                    installment_number=num,
                    label=label,
                    due_date=due_date,
                    amount=float(scheme.price),
                    is_paid=payment is not None,
                    paid_at=payment.paid_at if payment else None,
                    payment_method=payment.payment_method if payment else None,
                    payment_id=str(payment.id) if payment else None,
                )
            )
        return items

    def _format_member_response(self, member: SchemeMember, scheme: Scheme) -> SchemeMemberResponse:
        schedule = self._build_installment_schedule(member, scheme)
        payments = [
            SchemePaymentResponse(
                id=str(p.id),
                scheme_id=str(p.scheme_id),
                member_id=str(p.member_id),
                installment_number=p.installment_number,
                installment_label=p.installment_label,
                amount=float(p.amount),
                status=p.status,
                payment_method=p.payment_method,
                paid_at=p.paid_at,
                transaction_id=p.transaction_id,
                notes=p.notes,
            )
            for p in (member.payments or [])
        ]

        return SchemeMemberResponse(
            id=str(member.id),
            scheme_id=str(member.scheme_id),
            shop_id=str(member.shop_id),
            customer_id=str(member.customer_id) if member.customer_id else None,
            customer_name=member.customer_name,
            customer_phone=normalize_phone_with_country_code(member.customer_phone),
            customer_address=member.customer_address,
            member_number=member.member_number,
            status=member.status,
            joined_at=member.joined_at,
            total_installments=member.total_installments,
            paid_installments=member.paid_installments,
            notes=member.notes,
            payments=payments,
            installment_schedule=schedule,
        )

    async def _send_scheme_enrollment_email(
        self,
        shop_id: uuid.UUID,
        scheme: Scheme,
        member: SchemeMember,
        payment_method: str = "cash",
    ):
        """Send immediate email notification to shop owner & platform admins when a customer enrolls."""
        import logging
        logger = logging.getLogger(__name__)
        try:
            from app.database.session import async_session_factory
            from app.models.shop import Shop
            from app.models.user import User
            from app.services.email_service import email_service
            import pytz

            settings = get_settings()

            owner_email = None
            shop_name = "Shop"
            async with async_session_factory() as session:
                shop_res = await session.execute(select(Shop).where(Shop.id == shop_id))
                s_obj = shop_res.scalar_one_or_none()
                if s_obj:
                    shop_name = s_obj.name or "Shop"
                    if s_obj.user_id:
                        user_res = await session.execute(select(User).where(User.id == s_obj.user_id))
                        user_obj = user_res.scalar_one_or_none()
                        if user_obj and user_obj.email:
                            owner_email = user_obj.email

            recipients = set()
            if owner_email and "@" in str(owner_email):
                recipients.add(str(owner_email).strip().lower())

            admin_email = getattr(settings, "ADMIN_NOTIFICATION_EMAIL", None)
            if admin_email and "@" in str(admin_email):
                recipients.add(str(admin_email).strip().lower())

            if not recipients:
                logger.info(f"No recipients found for scheme enrollment email for shop {shop_id}")
                return

            ist_tz = pytz.timezone("Asia/Kolkata")
            joined_dt = member.joined_at
            if joined_dt:
                if joined_dt.tzinfo is None:
                    joined_dt = pytz.utc.localize(joined_dt)
                joined_str = joined_dt.astimezone(ist_tz).strftime("%d %b %Y, %I:%M %p IST")
            else:
                joined_str = datetime.now(ist_tz).strftime("%d %b %Y, %I:%M %p IST")

            for recipient in recipients:
                await email_service.send_scheme_enrollment_email(
                    email=recipient,
                    shop_name=shop_name,
                    scheme_title=scheme.title,
                    member_number=member.member_number,
                    customer_name=member.customer_name,
                    customer_phone=member.customer_phone,
                    customer_address=member.customer_address,
                    installment_amount=float(scheme.price or 0.0),
                    term_duration=scheme.term_duration,
                    frequency=scheme.frequency,
                    term_unit=scheme.term_unit,
                    payment_method=payment_method,
                    joined_at_str=joined_str,
                )
        except Exception as e:
            logger.error(f"Failed to send scheme enrollment email for member {member.id}: {e}", exc_info=True)

