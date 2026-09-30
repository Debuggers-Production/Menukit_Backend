"""Unit and Integration Tests for Order Pricing, Fee Structure, Replacement, and Refund Logic.

Tests Cover:
1. ₹2.94 order pricing
2. ₹4.00 order pricing
3. ₹4 -> ₹1 replacement in a ₹6.94 order
4. Multiple-item replacement sequence
5. Replacement resulting in a refund
6. Replacement resulting in additional payment
7. Exact-price replacement
8. Decimal/rounding edge cases (e.g. ₹0.01, ₹0.03, ₹99.99, ₹1000.55)
9. Repeated replacement attempts and state integrity
10. Payment/refund amount consistency with Razorpay (paise subunit precision)
"""

import pytest
from decimal import Decimal
from app.core.pricing import (
    calculate_order_pricing,
    calculate_replacement,
    round_money,
    round_money_float,
    to_decimal,
    PLATFORM_FEE_RATE,
    GATEWAY_FEE_RATE,
    GATEWAY_GST_RATE,
    TOTAL_FEE_MULTIPLIER
)


def test_1_order_2_94_pricing():
    """Test Case 1: Order with subtotal ₹2.94."""
    subtotal = Decimal("2.94")
    pricing = calculate_order_pricing(subtotal, is_online=True)

    # platform_fee = 2.94 * 0.02 = 0.0588
    assert pricing.platform_fee_unrounded == pytest.approx(0.0588, abs=1e-6)
    assert pricing.platform_fee == 0.06

    # gateway_fee = 2.94 * 0.03 = 0.0882
    assert pricing.gateway_fee_unrounded == pytest.approx(0.0882, abs=1e-6)
    assert pricing.gateway_fee == 0.09

    # gateway_gst = 0.0882 * 0.18 = 0.015876
    assert pricing.gateway_gst_unrounded == pytest.approx(0.015876, abs=1e-6)
    assert pricing.gateway_gst == 0.02

    # total_pg_fee = 0.0882 + 0.015876 = 0.104076 (rounded: 0.10)
    assert pricing.total_pg_fee_unrounded == pytest.approx(0.104076, abs=1e-6)
    assert pricing.total_pg_fee == 0.10

    # total before rounding: 2.94 + 0.0588 + 0.0882 + 0.015876 = 3.102876
    assert pricing.total_payable_unrounded == pytest.approx(3.102876, abs=1e-6)
    # final payable: 3.10
    assert pricing.total_payable == 3.10
    assert pricing.amount_subunits == 310


def test_2_order_4_00_pricing():
    """Test Case 2: Order with subtotal ₹4.00."""
    subtotal = Decimal("4.00")
    pricing = calculate_order_pricing(subtotal, is_online=True)

    # platform_fee = 4.00 * 0.02 = 0.08
    assert pricing.platform_fee == 0.08

    # gateway_fee = 4.00 * 0.03 = 0.12
    assert pricing.gateway_fee == 0.12

    # gateway_gst = 0.12 * 0.18 = 0.0216
    assert pricing.gateway_gst == 0.02

    # total_payable_unrounded = 4.00 + 0.08 + 0.12 + 0.0216 = 4.2216
    assert pricing.total_payable_unrounded == pytest.approx(4.2216, abs=1e-6)
    # final payable: 4.22
    assert pricing.total_payable == 4.22
    assert pricing.amount_subunits == 422


def test_3_replacement_4_to_1_in_order():
    """Test Case 3: ₹4 -> ₹1 replacement in order with Item A ₹4.00 + Item B ₹2.94."""
    orig_subtotal = Decimal("6.94")
    orig_pricing = calculate_order_pricing(orig_subtotal, is_online=True)
    # 6.94 * 1.0554 = 7.324476 -> 7.32
    assert orig_pricing.total_payable == 7.32

    # Replace Item A (₹4.00) with (₹1.00): new subtotal = ₹3.94
    new_subtotal = Decimal("3.94")
    rep_result = calculate_replacement(
        original_paid_amount=orig_pricing.total_payable,
        new_subtotal=new_subtotal,
        old_subtotal=orig_subtotal,
        is_online=True
    )

    # 3.94 * 1.0554 = 4.158276 -> 4.16
    assert rep_result.new_total_payable == 4.16
    assert rep_result.action == "refund"
    # refund_amount = 7.32 - 4.16 = 3.16
    assert rep_result.refund_amount == 3.16
    assert rep_result.additional_payment == 0.0
    assert rep_result.difference == -3.16


def test_4_multiple_item_replacement():
    """Test Case 4: Sequential multiple-item replacements."""
    # Order: Item 1 (₹10) + Item 2 (₹20) + Item 3 (₹30) = ₹60.00
    subtotal_step0 = Decimal("60.00")
    paid_step0 = calculate_order_pricing(subtotal_step0, is_online=True).total_payable
    assert paid_step0 == 63.32  # 60 * 1.0554 = 63.324 -> 63.32

    # Step 1: Replace Item 1 (₹10 -> ₹5): new subtotal = ₹55.00
    subtotal_step1 = Decimal("55.00")
    rep_step1 = calculate_replacement(
        original_paid_amount=paid_step0,
        new_subtotal=subtotal_step1,
        is_online=True
    )
    # 55 * 1.0554 = 58.047 -> 58.05
    assert rep_step1.new_total_payable == 58.05
    assert rep_step1.action == "refund"
    assert rep_step1.refund_amount == 5.27  # 63.32 - 58.05 = 5.27

    # Step 2: Now replace Item 2 (₹20 -> ₹25) from current effective paid of ₹58.05
    subtotal_step2 = Decimal("60.00")
    rep_step2 = calculate_replacement(
        original_paid_amount=rep_step1.new_total_payable,
        new_subtotal=subtotal_step2,
        is_online=True
    )
    assert rep_step2.new_total_payable == 63.32
    assert rep_step2.action == "payment_due"
    assert rep_step2.additional_payment == 5.27
    assert rep_step2.refund_amount == 0.0


def test_5_replacement_resulting_in_refund():
    """Test Case 5: Large single item price reduction resulting in refund."""
    orig_subtotal = Decimal("100.00")
    orig_paid = calculate_order_pricing(orig_subtotal, is_online=True).total_payable
    assert orig_paid == 105.54

    # Replace ₹100 item with ₹50 item
    new_subtotal = Decimal("50.00")
    rep = calculate_replacement(orig_paid, new_subtotal, is_online=True)
    assert rep.new_total_payable == 52.77  # 50 * 1.0554 = 52.77
    assert rep.action == "refund"
    assert rep.refund_amount == 52.77      # 105.54 - 52.77 = 52.77
    assert rep.additional_payment == 0.0


def test_6_replacement_resulting_in_additional_payment():
    """Test Case 6: Item price increase requiring additional customer payment."""
    orig_subtotal = Decimal("50.00")
    orig_paid = calculate_order_pricing(orig_subtotal, is_online=True).total_payable
    assert orig_paid == 52.77

    # Replace ₹50 item with ₹100 item
    new_subtotal = Decimal("100.00")
    rep = calculate_replacement(orig_paid, new_subtotal, is_online=True)
    assert rep.new_total_payable == 105.54
    assert rep.action == "payment_due"
    assert rep.additional_payment == 52.77
    assert rep.refund_amount == 0.0


def test_7_exact_price_replacement():
    """Test Case 7: Exact-price replacement (no refund, no extra payment)."""
    orig_subtotal = Decimal("50.00")
    orig_paid = calculate_order_pricing(orig_subtotal, is_online=True).total_payable

    # Replace ₹50 item with different ₹50 item
    new_subtotal = Decimal("50.00")
    rep = calculate_replacement(orig_paid, new_subtotal, is_online=True)
    assert rep.new_total_payable == orig_paid
    assert rep.action == "none"
    assert rep.refund_amount == 0.0
    assert rep.additional_payment == 0.0
    assert rep.difference == 0.0


def test_8_decimal_rounding_edge_cases():
    """Test Case 8: Smallest currency units and fractional edge cases."""
    # ₹0.01 order
    p_001 = calculate_order_pricing("0.01", is_online=True)
    # 0.01 * 1.0554 = 0.010554 -> 0.01
    assert p_001.total_payable == 0.01
    assert p_001.amount_subunits == 1

    # ₹0.05 order
    p_005 = calculate_order_pricing("0.05", is_online=True)
    # 0.05 * 1.0554 = 0.05277 -> 0.05
    assert p_005.total_payable == 0.05
    assert p_005.amount_subunits == 5

    # ₹99.99 order
    p_9999 = calculate_order_pricing("99.99", is_online=True)
    # 99.99 * 1.0554 = 105.529446 -> 105.53
    assert p_9999.total_payable == 105.53
    assert p_9999.amount_subunits == 10553

    # ₹1000.55 order
    p_1000 = calculate_order_pricing("1000.55", is_online=True)
    # 1000.55 * 1.0554 = 1055.98047 -> 1055.98
    assert p_1000.total_payable == 1055.98
    assert p_1000.amount_subunits == 105598


def test_9_repeated_replacement_idempotency():
    """Test Case 9: Repeated calculation produces consistent, non-drifting results."""
    base = Decimal("50.00")
    paid = calculate_order_pricing(base, is_online=True).total_payable

    for _ in range(5):
        rep = calculate_replacement(paid, Decimal("40.00"), is_online=True)
        # 40 * 1.0554 = 42.216 -> 42.22
        assert rep.new_total_payable == 42.22
        assert rep.refund_amount == 10.55
        assert rep.action == "refund"


def test_10_razorpay_paise_consistency():
    """Test Case 10: Razorpay amount (paise) consistency across pricing and replacements."""
    # Subtotal ₹2.94 -> 310 paise
    p1 = calculate_order_pricing("2.94", is_online=True)
    assert p1.amount_subunits == 310
    assert int(round(p1.total_payable * 100)) == p1.amount_subunits

    # Subtotal ₹4.00 -> 422 paise
    p2 = calculate_order_pricing("4.00", is_online=True)
    assert p2.amount_subunits == 422
    assert int(round(p2.total_payable * 100)) == p2.amount_subunits

    # Cash order -> zero platform & gateway fees added to customer payable
    p_cash = calculate_order_pricing("50.00", is_online=False)
    assert p_cash.platform_fee == 0.0
    assert p_cash.gateway_fee == 0.0
    assert p_cash.total_pg_fee == 0.0
    assert p_cash.total_payable == 50.00
    assert p_cash.amount_subunits == 5000


if __name__ == "__main__":
    pytest.main(["-v", __file__])
