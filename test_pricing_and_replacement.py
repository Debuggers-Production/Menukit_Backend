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

    # gateway_gst = 0.0882 * 0.18 = 0.015876 (3rd decimal digit is 5 -> strict > 5 rule rounds down to 0.01)
    assert pricing.gateway_gst_unrounded == pytest.approx(0.015876, abs=1e-6)
    assert pricing.gateway_gst == 0.01

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

    # Replace Item A (₹4.00) with (₹1.00): new subtotal = ₹3.94 (product difference = ₹3.00)
    new_subtotal = Decimal("3.94")
    rep_result = calculate_replacement(
        original_paid_amount=orig_pricing.total_payable,
        new_subtotal=new_subtotal,
        old_subtotal=orig_subtotal,
        is_online=True
    )

    assert rep_result.action == "refund"
    # refund_amount = 6.94 - 3.94 = 3.00 (pure product difference, charges are non-refundable)
    assert rep_result.refund_amount == 3.00
    assert rep_result.additional_payment == 0.0
    assert rep_result.difference == -3.00


def test_4_multiple_item_replacement():
    """Test Case 4: Sequential multiple-item replacements."""
    # Order: Item 1 (₹10) + Item 2 (₹20) + Item 3 (₹30) = ₹60.00
    subtotal_step0 = Decimal("60.00")
    paid_step0 = calculate_order_pricing(subtotal_step0, is_online=True).total_payable
    assert paid_step0 == 63.32  # 60 * 1.0554 = 63.324 -> 63.32

    # Step 1: Replace Item 1 (₹10 -> ₹5): new subtotal = ₹55.00 (product difference = ₹5.00)
    subtotal_step1 = Decimal("55.00")
    rep_step1 = calculate_replacement(
        original_paid_amount=paid_step0,
        new_subtotal=subtotal_step1,
        old_subtotal=subtotal_step0,
        is_online=True
    )
    assert rep_step1.action == "refund"
    assert rep_step1.refund_amount == 5.00  # 60.00 - 55.00 = 5.00
    assert rep_step1.difference == -5.00

    # Step 2: Now replace Item 2 (₹20 -> ₹25): new subtotal = ₹60.00 (product difference = +₹5.00)
    subtotal_step2 = Decimal("60.00")
    rep_step2 = calculate_replacement(
        original_paid_amount=rep_step1.new_total_payable,
        new_subtotal=subtotal_step2,
        old_subtotal=subtotal_step1,
        is_online=True
    )
    assert rep_step2.action == "payment_due"
    # Additional payment on extra ₹5.00 online = 5.00 * 1.0554 = 5.277 -> rounded strict > 5 = 5.28
    assert rep_step2.additional_payment == 5.28
    assert rep_step2.refund_amount == 0.0


def test_5_replacement_resulting_in_refund():
    """Test Case 5: Large single item price reduction resulting in refund."""
    orig_subtotal = Decimal("100.00")
    orig_paid = calculate_order_pricing(orig_subtotal, is_online=True).total_payable
    assert orig_paid == 105.54

    # Replace ₹100 item with ₹50 item (product difference = ₹50.00)
    new_subtotal = Decimal("50.00")
    rep = calculate_replacement(orig_paid, new_subtotal, old_subtotal=orig_subtotal, is_online=True)
    assert rep.action == "refund"
    assert rep.refund_amount == 50.00      # 100.00 - 50.00 = 50.00
    assert rep.additional_payment == 0.0
    assert rep.difference == -50.00


def test_6_replacement_resulting_in_additional_payment():
    """Test Case 6: Item price increase requiring additional customer payment."""
    orig_subtotal = Decimal("50.00")
    orig_paid = calculate_order_pricing(orig_subtotal, is_online=True).total_payable
    assert orig_paid == 52.77

    # Replace ₹50 item with ₹100 item (product difference = +₹50.00)
    new_subtotal = Decimal("100.00")
    rep = calculate_replacement(orig_paid, new_subtotal, old_subtotal=orig_subtotal, is_online=True)
    assert rep.action == "payment_due"
    assert rep.additional_payment == 52.77  # 50 * 1.0554 = 52.77
    assert rep.refund_amount == 0.0


def test_7_exact_price_replacement():
    """Test Case 7: Exact-price replacement (no refund, no extra payment)."""
    orig_subtotal = Decimal("50.00")
    orig_paid = calculate_order_pricing(orig_subtotal, is_online=True).total_payable

    # Replace ₹50 item with different ₹50 item
    new_subtotal = Decimal("50.00")
    rep = calculate_replacement(orig_paid, new_subtotal, old_subtotal=orig_subtotal, is_online=True)
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
        rep = calculate_replacement(paid, Decimal("40.00"), old_subtotal=base, is_online=True)
        assert rep.refund_amount == 10.00
        assert rep.action == "refund"
        assert rep.difference == -10.00


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


def test_11_cancellation_of_higher_replacement_refunds_exact_paid_difference():
    """Test Case 11: Cancelling an item that replaced a cheaper item (where price diff was unpaid) refunds strictly the paid predecessor amount (₹1.00)."""
    class MockItem:
        def __init__(self, name, price, qty, is_cancelled, reason):
            self.name = name
            self.price = price
            self.quantity = qty
            self.is_cancelled = is_cancelled
            self.cancellation_reason = reason

    class MockOrder:
        def __init__(self, items, payment_status, payment_method, session_id):
            self.items = items
            self.payment_status = payment_status
            self.payment_method = payment_method
            self.payment_session_id = session_id
            self.razorpay_order_id = None
            self.total_amount = 2.00

    from app.services.order_service import OrderService
    # Standalone mock order service instance without DB
    dummy_service = OrderService.__new__(OrderService)

    # Order with:
    # 1. Pattani Vedi (₹2.00, replaced by Kambi Mathapu, ₹1.00 refunded previously)
    # 2. Kambi Mathapu (₹1.00, replaced by Pattani Vedi, ₹1.00 unpaid diff)
    # 3. Pattani Vedi (₹2.00 active)
    it1 = MockItem("Pattani Vedi", 2.0, 1, True, "Replaced with Kambi Mathapu (Customer changed preference)")
    it2 = MockItem("Kambi Mathapu", 1.0, 1, True, "Replaced with Pattani Vedi (Customer changed preference)")
    it3 = MockItem("Pattani Vedi", 2.0, 1, False, None)

    order = MockOrder([it1, it2, it3], "pending", "online", "pay_mock_123")
    refundable_amt = dummy_service._calculate_refundable_product_amount(order, it3)

    # Must refund strictly the paid predecessor value (₹1.00), not the full active price (₹2.00) or ₹0.00
    assert refundable_amt == 1.00


def test_12_replacement_credit_calculation_chain():
    """Test Case 12: Chain replacement ₹2 -> ₹1 -> ₹2 calculates exact ₹1.00 paid credit and ₹1.00 due difference."""
    from app.core.pricing import calculate_order_replacement_credit, calculate_order_pricing

    class MockItem:
        def __init__(self, name, price, qty, is_cancelled, reason):
            self.name = name
            self.price = price
            self.quantity = qty
            self.is_cancelled = is_cancelled
            self.cancellation_reason = reason

    # Step 1: 2.00 Pattani Vedi (cancelled, replaced with Kambi Mathapu)
    # Step 2: 1.00 Kambi Mathapu (cancelled, replaced with Pattani Vedi)
    # Step 3: 2.00 Pattani Vedi (active)
    it1 = MockItem("Pattani Vedi", 2.0, 1, True, "Replaced with Kambi Mathapu (Out of stock)")
    it2 = MockItem("Kambi Mathapu", 1.0, 1, True, "Replaced with Pattani Vedi (Preference)")
    it3 = MockItem("Pattani Vedi", 2.0, 1, False, None)

    items = [it1, it2, it3]
    credit = calculate_order_replacement_credit(items, is_paid=False)
    assert credit == 1.00

    active_subtotal = 2.00
    remaining_product_due = active_subtotal - credit
    assert remaining_product_due == 1.00

    # Pricing on remaining difference (1.00 subtotal)
    pricing = calculate_order_pricing(remaining_product_due, is_online=True)
    assert pricing.platform_fee == 0.02
    assert pricing.gateway_fee == 0.03
    assert pricing.gateway_gst == 0.00
    assert pricing.total_payable == 1.05
    assert pricing.amount_subunits == 105


if __name__ == "__main__":
    pytest.main(["-v", __file__])

