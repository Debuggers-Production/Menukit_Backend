"""Centralized Order Pricing, Fee Calculation, and Replacement Logic.

RULES:
- Platform fee = 2% of the item/order subtotal
- Payment gateway fee = 3% of the item/order subtotal
- GST = 18% of the payment gateway fee
- No other hidden fees.
- Total payable (online) = subtotal + platform_fee + gateway_fee + gateway_gst (equivalent: subtotal * 1.0554)
- Decimal arithmetic with NO intermediate rounding; only final values rounded to 2 decimal places.
- Backend is the single source of truth.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Union, Optional
from pydantic import BaseModel

PLATFORM_FEE_RATE = Decimal("0.02")        # 2%
GATEWAY_FEE_RATE = Decimal("0.03")         # 3%
GATEWAY_GST_RATE = Decimal("0.18")         # 18% on gateway fee
COMBINED_GATEWAY_RATE = GATEWAY_FEE_RATE * (Decimal("1") + GATEWAY_GST_RATE)  # 0.0354 (3.54%)
TOTAL_FEE_MULTIPLIER = Decimal("1") + PLATFORM_FEE_RATE + COMBINED_GATEWAY_RATE  # 1.0554

TWO_PLACES = Decimal("0.01")


def to_decimal(val: Union[float, int, str, Decimal, None]) -> Decimal:
    """Safely convert any numeric input to Decimal without float binary representation artifacts."""
    if val is None:
        return Decimal("0.00")
    if isinstance(val, Decimal):
        return val
    return Decimal(str(val))


def round_money(val: Decimal) -> Decimal:
    """Round Decimal to exactly 2 decimal places using standard ROUND_HALF_UP."""
    return val.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def round_money_float(val: Union[float, int, str, Decimal, None]) -> float:
    """Round value to 2 decimal places and return as float."""
    return float(round_money(to_decimal(val)))


class OrderPricingResult(BaseModel):
    subtotal: float
    platform_fee_unrounded: float
    gateway_fee_unrounded: float
    gateway_gst_unrounded: float
    total_pg_fee_unrounded: float
    total_payable_unrounded: float

    # Rounded values for display & charging
    platform_fee: float
    gateway_fee: float
    gateway_gst: float
    total_pg_fee: float       # Gateway fee + Gateway GST combined
    total_payable: float
    amount_subunits: int      # Amount in paise (cents) for payment gateways


def calculate_order_pricing(
    subtotal: Union[float, int, str, Decimal],
    is_online: bool = True
) -> OrderPricingResult:
    """
    Calculate platform fee, payment gateway fee, gateway GST, and total payable
    using full Decimal precision with no intermediate rounding.
    """
    sub_d = to_decimal(subtotal)
    if sub_d < Decimal("0"):
        sub_d = Decimal("0")

    if not is_online:
        rounded_sub = round_money(sub_d)
        return OrderPricingResult(
            subtotal=float(rounded_sub),
            platform_fee_unrounded=0.0,
            gateway_fee_unrounded=0.0,
            gateway_gst_unrounded=0.0,
            total_pg_fee_unrounded=0.0,
            total_payable_unrounded=float(sub_d),
            platform_fee=0.0,
            gateway_fee=0.0,
            gateway_gst=0.0,
            total_pg_fee=0.0,
            total_payable=float(rounded_sub),
            amount_subunits=int(rounded_sub * 100)
        )

    platform_fee_d = sub_d * PLATFORM_FEE_RATE
    gateway_fee_d = sub_d * GATEWAY_FEE_RATE
    gateway_gst_d = gateway_fee_d * GATEWAY_GST_RATE
    total_pg_fee_d = gateway_fee_d + gateway_gst_d
    total_payable_d = sub_d + platform_fee_d + total_pg_fee_d

    rounded_sub = round_money(sub_d)
    rounded_plat = round_money(platform_fee_d)
    rounded_gw = round_money(gateway_fee_d)
    rounded_gst = round_money(gateway_gst_d)
    rounded_total_pg = round_money(total_pg_fee_d)
    rounded_payable = round_money(total_payable_d)

    return OrderPricingResult(
        subtotal=float(rounded_sub),
        platform_fee_unrounded=float(platform_fee_d),
        gateway_fee_unrounded=float(gateway_fee_d),
        gateway_gst_unrounded=float(gateway_gst_d),
        total_pg_fee_unrounded=float(total_pg_fee_d),
        total_payable_unrounded=float(total_payable_d),
        platform_fee=float(rounded_plat),
        gateway_fee=float(rounded_gw),
        gateway_gst=float(rounded_gst),
        total_pg_fee=float(rounded_total_pg),
        total_payable=float(rounded_payable),
        amount_subunits=int(rounded_payable * 100)
    )


class ReplacementCalculationResult(BaseModel):
    old_subtotal: float
    new_subtotal: float
    original_paid_amount: float
    new_total_payable: float
    difference: float          # new_total_payable - original_paid_amount
    refund_amount: float       # max(0, original_paid_amount - new_total_payable)
    additional_payment: float  # max(0, new_total_payable - original_paid_amount)
    action: str                # 'refund', 'payment_due', 'none'
    pricing: OrderPricingResult


def calculate_replacement(
    original_paid_amount: Union[float, int, str, Decimal],
    new_subtotal: Union[float, int, str, Decimal],
    old_subtotal: Union[float, int, str, Decimal] = 0.0,
    is_online: bool = True
) -> ReplacementCalculationResult:
    """
    Calculate replacement refund or additional payment required by building
    the complete NEW order state and pricing it through the exact fee engine.
    """
    orig_paid_d = round_money(to_decimal(original_paid_amount))
    new_pricing = calculate_order_pricing(new_subtotal, is_online=is_online)
    new_total_d = to_decimal(new_pricing.total_payable)

    diff_d = round_money(new_total_d - orig_paid_d)

    if diff_d < Decimal("0"):
        refund_d = abs(diff_d)
        action = "refund"
        add_pay_d = Decimal("0")
    elif diff_d > Decimal("0"):
        refund_d = Decimal("0")
        add_pay_d = diff_d
        action = "payment_due"
    else:
        refund_d = Decimal("0")
        add_pay_d = Decimal("0")
        action = "none"

    return ReplacementCalculationResult(
        old_subtotal=float(round_money(to_decimal(old_subtotal))),
        new_subtotal=float(round_money(to_decimal(new_subtotal))),
        original_paid_amount=float(orig_paid_d),
        new_total_payable=float(new_total_d),
        difference=float(diff_d),
        refund_amount=float(refund_d),
        additional_payment=float(add_pay_d),
        action=action,
        pricing=new_pricing
    )
