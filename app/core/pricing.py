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


import math

def round_strict_two_decimals(val: Union[float, int, str, Decimal, None]) -> float:
    """
    Round to 2 decimal places ONLY if the 3rd decimal digit is strictly greater than 5 (> 5).
    If <= 5 (e.g. 1.0554 or 1.054), it stays at 1.05.
    If > 5 (e.g. 1.056 or 1.058), it rounds up to 1.06.
    """
    if val is None:
        return 0.0
    val_float = float(val)
    shifted = abs(val_float) * 1000.0
    third_digit = int(shifted + 1e-9) % 10
    sign = 1.0 if val_float >= 0 else -1.0
    if third_digit > 5:
        return sign * (math.ceil(abs(val_float) * 100.0 - 1e-9) / 100.0)
    else:
        return sign * (math.floor(abs(val_float) * 100.0 + 1e-9) / 100.0)


def round_money(val: Union[float, int, str, Decimal, None]) -> Decimal:
    """Round value to 2 decimal places using strict > 5 rounding."""
    return Decimal(str(round_strict_two_decimals(val)))


def round_money_float(val: Union[float, int, str, Decimal, None]) -> float:
    """Round value to 2 decimal places and return as float."""
    return round_strict_two_decimals(val)


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
    Calculate platform fee (2%), payment gateway fee (3%), and GST (18% on PG fee).
    Total payable = subtotal + 2% + 3% + 18% of 3%.
    Uses strict > 5 rounding on 3rd decimal place.
    """
    clean_sub = max(0.0, float(subtotal or 0.0))

    if not is_online:
        rounded_sub = round_strict_two_decimals(clean_sub)
        return OrderPricingResult(
            subtotal=rounded_sub,
            platform_fee_unrounded=0.0,
            gateway_fee_unrounded=0.0,
            gateway_gst_unrounded=0.0,
            total_pg_fee_unrounded=0.0,
            total_payable_unrounded=clean_sub,
            platform_fee=0.0,
            gateway_fee=0.0,
            gateway_gst=0.0,
            total_pg_fee=0.0,
            total_payable=rounded_sub,
            amount_subunits=int(round(rounded_sub * 100))
        )

    # 1. 2% Platform Fee
    platform_fee_unrounded = clean_sub * 0.02

    # 2. 3% Payment Gateway Fee
    gateway_fee_unrounded = clean_sub * 0.03

    # 3. 18% GST on the 3% Payment Gateway Fee
    gateway_gst_unrounded = gateway_fee_unrounded * 0.18

    # 4. Combined Total PG Fee
    total_pg_fee_unrounded = gateway_fee_unrounded + gateway_gst_unrounded

    # 5. Total Unrounded
    total_payable_unrounded = clean_sub + platform_fee_unrounded + total_pg_fee_unrounded

    # Strict > 5 rounding
    rounded_sub = round_strict_two_decimals(clean_sub)
    rounded_plat = round_strict_two_decimals(platform_fee_unrounded)
    rounded_gw = round_strict_two_decimals(gateway_fee_unrounded)
    rounded_gst = round_strict_two_decimals(gateway_gst_unrounded)
    rounded_total_pg = round_strict_two_decimals(total_pg_fee_unrounded)
    rounded_payable = round_strict_two_decimals(total_payable_unrounded)

    return OrderPricingResult(
        subtotal=rounded_sub,
        platform_fee_unrounded=platform_fee_unrounded,
        gateway_fee_unrounded=gateway_fee_unrounded,
        gateway_gst_unrounded=gateway_gst_unrounded,
        total_pg_fee_unrounded=total_pg_fee_unrounded,
        total_payable_unrounded=total_payable_unrounded,
        platform_fee=rounded_plat,
        gateway_fee=rounded_gw,
        gateway_gst=rounded_gst,
        total_pg_fee=rounded_total_pg,
        total_payable=rounded_payable,
        amount_subunits=int(round(rounded_payable * 100))
    )


class ReplacementCalculationResult(BaseModel):
    old_subtotal: float
    new_subtotal: float
    original_paid_amount: float
    new_total_payable: float
    product_difference: float  # Pure product difference without charges (new_subtotal - old_subtotal)
    difference: float          # Difference displayed on admin side (always pure product difference)
    refund_amount: float       # Pure product refund amount
    additional_payment: float  # Total customer payable on extra amount with online charges included
    action: str                # 'refund', 'payment_due', 'none'
    pricing: OrderPricingResult


def calculate_replacement(
    original_paid_amount: Union[float, int, str, Decimal],
    new_subtotal: Union[float, int, str, Decimal],
    old_subtotal: Union[float, int, str, Decimal] = 0.0,
    is_online: bool = True
) -> ReplacementCalculationResult:
    """
    Calculate replacement refund or additional payment required.

    RULES:
    1. Admin side always displays the pure product difference without charges (difference = new_subtotal - old_subtotal).
    2. If new_subtotal < old_subtotal:
       Refund is strictly the product price difference (old_subtotal - new_subtotal).
       Prior convenience, platform, and payment gateway fees are non-refundable.
    3. If new_subtotal > old_subtotal:
       additional_payment sent to customer/WhatsApp includes the online fees on that extra amount.
    4. If new_subtotal == old_subtotal:
       No refund and no extra payment.
    """
    old_sub_d = round_money(to_decimal(old_subtotal))
    new_sub_d = round_money(to_decimal(new_subtotal))
    orig_paid_d = round_money(to_decimal(original_paid_amount))

    # Pure product price difference without charges
    product_diff_d = new_sub_d - old_sub_d
    diff_d = product_diff_d

    new_pricing = calculate_order_pricing(new_sub_d, is_online=is_online)

    if product_diff_d < Decimal("0"):
        # Cheaper item replacement: refund purely the product price difference without charges
        refund_d = round_money(abs(product_diff_d))
        add_pay_d = Decimal("0")
        action = "refund"
    elif product_diff_d > Decimal("0"):
        # More expensive item replacement: extra product amount due (+ fee on the extra amount if online for customer)
        extra_subtotal = float(product_diff_d)
        if is_online:
            extra_pricing = calculate_order_pricing(extra_subtotal, is_online=True)
            add_pay_d = round_money(to_decimal(extra_pricing.total_payable))
        else:
            add_pay_d = round_money(to_decimal(extra_subtotal))
        refund_d = Decimal("0")
        action = "payment_due"
    else:
        refund_d = Decimal("0")
        add_pay_d = Decimal("0")
        action = "none"

    return ReplacementCalculationResult(
        old_subtotal=float(old_sub_d),
        new_subtotal=float(new_sub_d),
        original_paid_amount=float(orig_paid_d),
        new_total_payable=float(to_decimal(new_pricing.total_payable)),
        product_difference=float(product_diff_d),
        difference=float(diff_d),
        refund_amount=float(refund_d),
        additional_payment=float(add_pay_d),
        action=action,
        pricing=new_pricing
    )


def calculate_order_replacement_credit(items: list, is_paid: bool = True) -> float:
    """
    Calculate the total product credit already paid by customer across active and predecessor replacement items.
    
    For active replacement items:
    - Traces predecessor cancelled items matching 'Replaced with <item.name>'
    - Finds the net paid value carried forward
    
    For non-replacement active items in a paid order:
    - Customer paid the full item price.
    """
    if not items:
        return 0.0

    active_items = [it for it in items if not (it.get("is_cancelled") if isinstance(it, dict) else getattr(it, "is_cancelled", False))]
    replaced_cancelled = [
        it for it in items 
        if (it.get("is_cancelled") if isinstance(it, dict) else getattr(it, "is_cancelled", False)) and 
        str((it.get("cancellation_reason") if isinstance(it, dict) else getattr(it, "cancellation_reason", "")) or "").startswith("Replaced with")
    ]

    total_credit = 0.0
    for act in active_items:
        act_name = act.get("name", "") if isinstance(act, dict) else getattr(act, "name", "")
        act_price = float((act.get("price") if isinstance(act, dict) else getattr(act, "price", 0.0)) or 0.0)
        act_qty = int((act.get("quantity") if isinstance(act, dict) else getattr(act, "quantity", 1)) or 1)
        act_total = act_price * act_qty

        # Find direct predecessor in replaced_cancelled
        predecessor = next(
            (p for p in replaced_cancelled if str((p.get("cancellation_reason") if isinstance(p, dict) else getattr(p, "cancellation_reason", "")) or "").startswith(f"Replaced with {act_name}")),
            None
        )
        if predecessor:
            pred_price = float((predecessor.get("price") if isinstance(predecessor, dict) else getattr(predecessor, "price", 0.0)) or 0.0)
            pred_qty = int((predecessor.get("quantity") if isinstance(predecessor, dict) else getattr(predecessor, "quantity", 1)) or 1)
            pred_total = pred_price * pred_qty
            total_credit += min(act_total, pred_total)
        elif is_paid:
            total_credit += act_total

    return round(total_credit, 2)

