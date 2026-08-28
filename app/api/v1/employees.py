"""Employee management API endpoints."""

import uuid
import secrets
from typing import List

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database.session import get_db
from app.database.redis import get_redis
from app.core.deps import get_current_user, get_current_shop_context, require_permission
from app.core.exceptions import ForbiddenException, NotFoundException, ConflictException
from app.models.user import User
from app.models.shop import Shop
from app.models.employee import Employee
from app.schemas.employee import EmployeeCreate, EmployeeUpdate, EmployeeResponse
from app.schemas.common import MessageResponse
from app.services.email_service import EmailService

router = APIRouter(prefix="/employees", tags=["Team Management"])


@router.post("", response_model=EmployeeResponse)
async def invite_employee(
    data: EmployeeCreate,
    shop: Shop = Depends(require_permission("team", "write")),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Invite a new employee to the shop."""
    clean_email = data.email.strip().lower()

    # Check if attempting to invite the shop owner
    if current_user.email and clean_email == current_user.email.strip().lower():
        raise ConflictException("Cannot invite the shop owner as a team member.")

    # Check if already an employee
    stmt = select(Employee).where(Employee.shop_id == shop.id, Employee.email == clean_email)
    res = await db.execute(stmt)
    if res.scalar_one_or_none():
        raise ConflictException("Employee with this email already exists in this shop.")

    # Generate token
    token = secrets.token_urlsafe(32)

    employee = Employee(
        shop_id=shop.id,
        email=clean_email,
        permissions=data.permissions,
        status="pending",
        verification_token=token
    )
    db.add(employee)
    await db.flush()

    # Send email
    email_service = EmailService()
    await email_service.send_employee_invite_email(clean_email, token, shop.name)

    await db.commit()
    await db.refresh(employee)
    return _employee_to_response(employee)


@router.get("", response_model=List[EmployeeResponse])
async def list_employees(
    shop: Shop = Depends(require_permission("team", "read")),
    db: AsyncSession = Depends(get_db),
):
    """List all employees for the shop."""
    stmt = select(Employee).where(Employee.shop_id == shop.id).order_by(Employee.created_at.desc())
    res = await db.execute(stmt)
    employees = res.scalars().all()

    return [_employee_to_response(emp) for emp in employees]


@router.put("/{employee_id}", response_model=EmployeeResponse)
async def update_employee(
    employee_id: str,
    data: EmployeeUpdate,
    shop: Shop = Depends(require_permission("team", "write")),
    db: AsyncSession = Depends(get_db),
):
    """Update employee permissions."""
    stmt = select(Employee).where(Employee.id == uuid.UUID(employee_id), Employee.shop_id == shop.id)
    res = await db.execute(stmt)
    employee = res.scalar_one_or_none()

    if not employee:
        raise NotFoundException("Employee not found.")

    employee.permissions = data.permissions
    await db.commit()
    await db.refresh(employee)
    return _employee_to_response(employee)


@router.post("/request-deletion-otp", response_model=MessageResponse)
async def request_deletion_otp(
    target: str = Query("team_member", description="Target resource being deleted"),
    current_user: User = Depends(get_current_user),
    redis=Depends(get_redis),
):
    """Request an OTP sent to the current user's email to confirm deleting a team member."""
    from app.services.otp_service import OTPService
    from app.core.exceptions import RateLimitException

    otp_service = OTPService(redis)
    code = await otp_service.create_otp(current_user.email, rate_limit_type="deletion")
    if code is None:
        raise RateLimitException("Too many OTP requests. Please try again later.")

    email_service = EmailService()
    await email_service.send_deletion_otp_email(current_user.email, code, target=target)
    return MessageResponse(message=f"Deletion OTP code has been sent to {current_user.email}")


@router.delete("/{employee_id}", response_model=MessageResponse)
async def remove_employee(
    employee_id: str,
    code: str | None = Query(None, description="OTP verification code (required for active members)"),
    shop: Shop = Depends(require_permission("team", "write")),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis=Depends(get_redis),
):
    """Remove an employee from the shop. Active employees require OTP verification."""

    stmt = select(Employee).where(Employee.id == uuid.UUID(employee_id), Employee.shop_id == shop.id)
    res = await db.execute(stmt)
    employee = res.scalar_one_or_none()

    if not employee:
        raise NotFoundException("Employee not found.")

    # Active members require OTP verification
    if employee.status == "active":
        if not code:
            raise HTTPException(status_code=400, detail="OTP verification code is required to remove active team members.")
        from app.services.otp_service import OTPService
        otp_service = OTPService(redis)
        is_valid = await otp_service.verify_otp(current_user.email, code)
        if not is_valid:
            raise HTTPException(status_code=400, detail="Invalid or expired deletion OTP code")

    await db.delete(employee)
    await db.commit()
    return MessageResponse(message="Employee removed successfully.")


@router.get("/verify")
async def verify_employee(
    token: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Verify employee invitation token."""
    stmt = select(Employee).where(Employee.verification_token == token)
    res = await db.execute(stmt)
    employee = res.scalar_one_or_none()

    if not employee:
        raise HTTPException(status_code=400, detail="Invalid or expired verification link.")

    if employee.status == "active":
        return {"message": "Email is already verified. You can log in now."}

    # Mark as active
    employee.status = "active"
    employee.verification_token = None

    # Check if a User already exists with this email
    user_stmt = select(User).where(User.email == employee.email)
    user_res = await db.execute(user_stmt)
    user = user_res.scalar_one_or_none()

    if user:
        employee.user_id = user.id
        if user.role != "owner":
            user.role = "employee"

    await db.commit()
    return {"message": "Email verified successfully. You can log in now."}


@router.post("/{employee_id}/resend", response_model=MessageResponse)
async def resend_employee_invite(
    employee_id: str,
    shop: Shop = Depends(require_permission("team", "write")),
    db: AsyncSession = Depends(get_db),
):
    """Resend invitation email to a pending employee."""

    stmt = select(Employee).where(Employee.id == uuid.UUID(employee_id), Employee.shop_id == shop.id)
    res = await db.execute(stmt)
    employee = res.scalar_one_or_none()

    if not employee:
        raise NotFoundException("Employee not found.")

    if employee.status == "active":
        raise HTTPException(status_code=400, detail="This member has already accepted the invitation.")

    # Regenerate token and resend
    token = secrets.token_urlsafe(32)
    employee.verification_token = token

    email_service = EmailService()
    await email_service.send_employee_invite_email(employee.email, token, shop.name)

    await db.commit()
    return MessageResponse(message="Invitation resent successfully.")


def _employee_to_response(emp: Employee) -> EmployeeResponse:
    return EmployeeResponse(
        id=str(emp.id),
        shop_id=str(emp.shop_id),
        user_id=str(emp.user_id) if emp.user_id else None,
        email=emp.email,
        status=emp.status,
        permissions=emp.permissions,
        created_at=str(emp.created_at)
    )
