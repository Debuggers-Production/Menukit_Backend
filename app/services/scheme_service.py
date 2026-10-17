"""Service for Savings Scheme (Pandu) operations."""

import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional, List, Tuple, Dict, Any

from sqlalchemy import select, func, or_, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import hmac
import hashlib
import re

from app.models.scheme import Scheme, SchemeMember, SchemePayment
from app.models.customer import Customer
from app.models.shop import Shop
from app.core.config import get_settings
from app.core.pricing import calculate_order_pricing
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
)
from app.core.exceptions import NotFoundException, BadRequestException


class SchemeService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_schemes(self, shop_id: uuid.UUID) -> List[SchemeResponse]:
        """Get all schemes for a shop with high-level statistics."""
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
                    price=float(s.price),
                    frequency=s.frequency,
                    term_duration=s.term_duration,
                    term_unit=s.term_unit,
                    max_members=s.max_members,
                    items=s.items or [],
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
            price=float(scheme.price),
            frequency=scheme.frequency,
            term_duration=scheme.term_duration,
            term_unit=scheme.term_unit,
            max_members=scheme.max_members,
            items=scheme.items or [],
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
            price=data.price,
            frequency=data.frequency,
            term_duration=data.term_duration,
            term_unit=data.term_unit,
            max_members=data.max_members,
            items=[i.model_dump() for i in data.items],
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

        if has_active_customers:
            # When active customers exist, strictly allow only title and description updates
            restricted_fields = ["price", "frequency", "term_duration", "term_unit", "max_members", "items"]
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

        await self.db.delete(scheme)
        await self.db.commit()
        return True

    async def get_scheme_members(
        self, scheme_id: uuid.UUID, shop_id: uuid.UUID, search: Optional[str] = None
    ) -> List[SchemeMemberResponse]:
        """Get members of a scheme with installment payment progress."""
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

        # Check duplicate by phone in the same scheme
        phone_clean = data.customer_phone.strip()
        existing = any(m.customer_phone.strip() == phone_clean for m in scheme.members)
        if existing:
            raise BadRequestException(f"A member with phone {phone_clean} is already enrolled in this scheme.")

        # Resolve customer_id if not passed
        if not customer_id:
            cust_stmt = select(Customer).where(Customer.mobile_number == phone_clean)
            cust_res = await self.db.execute(cust_stmt)
            cust = cust_res.scalar_one_or_none()
            if cust:
                customer_id = cust.id
            else:
                try:
                    new_cust = Customer(
                        id=uuid.uuid4(),
                        name=data.customer_name.strip(),
                        mobile_number=phone_clean,
                        delivery_address=data.customer_address.strip() if data.customer_address else None,
                    )
                    self.db.add(new_cust)
                    await self.db.flush()
                    customer_id = new_cust.id
                except Exception:
                    pass

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

        await self.db.commit()

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

        await self.db.commit()

        # Re-fetch refreshed member
        refreshed_res = await self.db.execute(member_stmt)
        refreshed = refreshed_res.scalar_one()
        return self._format_member_response(refreshed, scheme)

    # ------------------ Public Methods ------------------

    async def get_public_schemes(self, shop_id: uuid.UUID) -> List[PublicSchemeResponse]:
        """Get active public schemes for customers on the public menu."""
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
                    price=float(s.price),
                    frequency=s.frequency,
                    term_duration=s.term_duration,
                    term_unit=s.term_unit,
                    max_members=s.max_members,
                    total_members=total_m,
                    remaining_spots=remaining_spots,
                    items=s.items or [],
                    status=s.status,
                )
            )
        return results

    async def public_join_scheme(
        self, scheme_id: uuid.UUID, shop_id: uuid.UUID, data: SchemeMemberCreate, customer_id: Optional[uuid.UUID] = None
    ) -> SchemeMemberResponse:
        """Public endpoint allowing a customer to join a scheme."""
        return await self.add_member(scheme_id, shop_id, data, customer_id)

    async def initiate_join_payment(
        self, scheme_id: uuid.UUID, shop_id: uuid.UUID, data: SchemePaymentInitiateRequest
    ) -> SchemePaymentInitiateResponse:
        """Initiate Razorpay order for enrolling in a scheme with 2% platform commission and 3% (+18% GST) PG fee."""
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

        phone_clean = data.customer_phone.strip()
        existing = any(m.customer_phone.strip() == phone_clean for m in scheme.members)
        if existing:
            raise BadRequestException(f"A member with phone {phone_clean} is already enrolled in this scheme.")

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
            customer_phone=data.customer_phone.strip(),
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
        digits_only = re.sub(r'\D', '', clean_phone)
        last_10 = digits_only[-10:] if len(digits_only) >= 10 else digits_only

        conditions = [SchemeMember.customer_phone == clean_phone]
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
                    price=float(scheme.price),
                    frequency=scheme.frequency,
                    term_duration=scheme.term_duration,
                    term_unit=scheme.term_unit,
                    customer_name=m.customer_name,
                    customer_phone=m.customer_phone,
                    member_number=m.member_number,
                    status=m.status,
                    joined_at=m.joined_at,
                    total_installments=m.total_installments,
                    paid_installments=m.paid_installments,
                    remaining_installments=remaining,
                    items=scheme.items or [],
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
            customer_phone=member.customer_phone,
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
