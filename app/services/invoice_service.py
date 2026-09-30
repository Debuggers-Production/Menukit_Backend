import os
import uuid
import base64
from datetime import datetime, timezone
from typing import Dict, Any, List

_CACHED_LOGO_B64 = None

def get_logo_data_uri() -> str:
    """Retrieve self-contained base64 data URI of the Menukit brand logo."""
    global _CACHED_LOGO_B64
    if _CACHED_LOGO_B64 is not None:
        return _CACHED_LOGO_B64

    possible_paths = [
        os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../Menukit_Frontend/public/menukit-logo.svg")),
        os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../Menukit_Frontend/src/assets/menukit-logo.svg")),
    ]
    for p in possible_paths:
        if os.path.exists(p):
            try:
                with open(p, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("utf-8")
                    _CACHED_LOGO_B64 = f"data:image/svg+xml;base64,{b64}"
                    return _CACHED_LOGO_B64
            except Exception:
                pass

    _CACHED_LOGO_B64 = "/menukit-logo.svg"
    return _CACHED_LOGO_B64

MODULE_TITLES = {
    "online-orders": "Online Ordering System",
    "new-member": "Member & Loyalty Registration",
    "member-count": "Member Counter Dashboard",
    "member-details": "Detailed Member Analytics",
    "search-data": "Customer Search Insights",
    "custom-theme": "Custom Brand Themes",
    "analytics-advanced": "Advanced Analytics",
    "analytics-advanced-filters": "Advanced Analytics Filters",
    "analytics-customer-insights": "Customer Retention Insights",
    "hide-discovery-badge": "Featured Discovery (No Menu Badge)"
}

MODULE_PRICES = {
    "online-orders": 129.0,
    "new-member": 99.0,
    "member-count": 99.0,
    "member-details": 129.0,
    "search-data": 69.0,
    "custom-theme": 69.0,
    "analytics-advanced": 129.0,
    "analytics-advanced-filters": 59.0,
    "analytics-customer-insights": 59.0,
    "hide-discovery-badge": 49.0
}


class InvoiceService:
    """Service to construct invoice metadata and HTML templates for subscriptions."""

    @staticmethod
    def generate_invoice_number(transaction_id: str | None = None) -> str:
        """Generate a clean invoice reference number (e.g., INV-20260807-9A1B)."""
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        unique_part = (transaction_id or uuid.uuid4().hex)[:6].upper()
        return f"INV-{date_str}-{unique_part}"

    @staticmethod
    def build_invoice_data(
        transaction: Any,
        user_email: str,
        shop_name: str = "SmartMenu Retailer",
        invoice_number: str | None = None
    ) -> Dict[str, Any]:
        """Construct structured invoice data from a PaymentTransaction."""
        inv_num = invoice_number or getattr(transaction, "invoice_number", None) or InvoiceService.generate_invoice_number(str(transaction.id))
        
        is_all_access = getattr(transaction, "is_all_access", False)
        purchased = getattr(transaction, "purchased_modules", []) or []
        billing_cycle = getattr(transaction, "billing_cycle", "monthly") or "monthly"
        
        items = []
        if is_all_access:
            base_price = 449.0 if billing_cycle == "monthly" else 4490.0
            items.append({
                "description": f"All-Access Package ({billing_cycle.capitalize()} Subscription)",
                "amount": base_price
            })
            base_amount = base_price
        else:
            base_amount = 0.0
            for mod in purchased:
                if str(mod).startswith("broadcast-credits-"):
                    cnt_str = str(mod).replace("broadcast-credits-", "")
                    try:
                        price = float(cnt_str)
                    except ValueError:
                        price = float(getattr(transaction, "amount", 0.0))
                    base_amount += price
                    items.append({
                        "description": f"WhatsApp Marketing Campaign Credits ({cnt_str} Credits Recharge)",
                        "amount": price
                    })
                else:
                    price = MODULE_PRICES.get(mod, 99.0)
                    if billing_cycle == "yearly":
                        price = price * 10.0 # Yearly discount multiplier
                    base_amount += price
                    items.append({
                        "description": f"{MODULE_TITLES.get(mod, mod)} ({billing_cycle.capitalize()})",
                        "amount": price
                    })
            if not items:
                base_amount = getattr(transaction, "amount", 0.0)
                items.append({
                    "description": f"Subscription Module ({billing_cycle.capitalize()})",
                    "amount": base_amount
                })

        # Gateway Fee Breakdown
        from app.core.pricing import calculate_order_pricing
        pricing = calculate_order_pricing(base_amount, is_online=True)
        total_gateway_fee = pricing.total_pg_fee
        total_amount = pricing.total_payable

        paid_at = getattr(transaction, "updated_at", None) or getattr(transaction, "created_at", None) or datetime.now(timezone.utc)
        paid_at_iso = ""
        try:
            from zoneinfo import ZoneInfo
            ist_tz = ZoneInfo("Asia/Kolkata")
            if isinstance(paid_at, datetime):
                if paid_at.tzinfo is None:
                    paid_at_utc = paid_at.replace(tzinfo=timezone.utc)
                else:
                    paid_at_utc = paid_at.astimezone(timezone.utc)
                paid_at_ist = paid_at_utc.astimezone(ist_tz)
                paid_at_str = paid_at_ist.strftime("%B %d, %Y %I:%M %p")
                paid_at_iso = paid_at_utc.isoformat()
            else:
                paid_at_str = str(paid_at)
                paid_at_iso = str(paid_at)
        except Exception:
            paid_at_str = paid_at.strftime("%B %d, %Y %I:%M %p") if isinstance(paid_at, datetime) else str(paid_at)
            paid_at_iso = str(paid_at)

        return {
            "invoice_number": inv_num,
            "user_email": user_email,
            "shop_name": shop_name,
            "order_id": getattr(transaction, "razorpay_order_id", "N/A"),
            "payment_id": getattr(transaction, "razorpay_payment_id", "N/A"),
            "currency": getattr(transaction, "currency", "INR"),
            "billing_cycle": billing_cycle,
            "paid_at": paid_at_str,
            "paid_at_iso": paid_at_iso,
            "items": items,
            "base_amount": base_amount,
            "gateway_fee": total_gateway_fee,
            "total_amount": total_amount,
        }

    @staticmethod
    def render_invoice_html(data: Dict[str, Any]) -> str:
        """Render a clean, responsive, printable HTML invoice."""
        logo_uri = get_logo_data_uri()
        items_html = ""
        for item in data["items"]:
            items_html += f"""
            <tr style="border-bottom: 1px solid #e2e8f0;">
                <td style="padding: 12px 16px; font-weight: 500; color: #1e293b;">{item['description']}</td>
                <td style="padding: 12px 16px; text-align: right; font-weight: 700; color: #0f172a;">₹{item['amount']:.2f}</td>
            </tr>
            """

        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Invoice {data['invoice_number']} - Menukit</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            background-color: #f8fafc;
            color: #334155;
            margin: 0;
            padding: 24px;
        }}
        .invoice-card {{
            max-width: 650px;
            margin: 0 auto;
            background: #ffffff;
            border-radius: 16px;
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.05);
            padding: 36px;
            border: 1px solid #e2e8f0;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 2px solid #f1f5f9;
            padding-bottom: 20px;
            margin-bottom: 24px;
        }}
        .brand {{
            font-size: 24px;
            font-weight: 900;
            color: #f97316;
            letter-spacing: -0.5px;
        }}
        .badge {{
            display: inline-block;
            background: #dcfce7;
            color: #15803d;
            font-size: 12px;
            font-weight: 800;
            padding: 4px 12px;
            border-radius: 9999px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .meta-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
            margin-bottom: 28px;
            font-size: 13px;
        }}
        .meta-box label {{
            display: block;
            font-size: 11px;
            text-transform: uppercase;
            color: #94a3b8;
            font-weight: 700;
            margin-bottom: 2px;
        }}
        .meta-box span {{
            font-weight: 700;
            color: #1e293b;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 24px;
        }}
        th {{
            background: #f8fafc;
            text-align: left;
            padding: 10px 16px;
            font-size: 11px;
            text-transform: uppercase;
            color: #64748b;
            font-weight: 700;
        }}
        .totals {{
            margin-left: auto;
            width: 260px;
            font-size: 13px;
        }}
        .totals-row {{
            display: flex;
            justify-content: space-between;
            padding: 6px 0;
            color: #64748b;
        }}
        .totals-row.grand {{
            border-top: 2px solid #e2e8f0;
            padding-top: 10px;
            margin-top: 6px;
            font-size: 16px;
            font-weight: 900;
            color: #0f172a;
        }}
        .print-btn {{
            display: block;
            width: 100%;
            text-align: center;
            background: #f97316;
            color: white;
            padding: 12px;
            border-radius: 12px;
            font-weight: 700;
            text-decoration: none;
            margin-top: 28px;
            cursor: pointer;
            border: none;
        }}
        @media print {{
            body {{ background: white; padding: 0; }}
            .invoice-card {{ box-shadow: none; border: none; padding: 0; width: 100%; }}
            .print-btn {{ display: none !important; }}
        }}
    </style>
</head>
<body>
    <div class="invoice-card">
        <div class="header">
            <div style="display: flex; align-items: center; gap: 14px;">
                <img src="{logo_uri}" alt="Menukit" style="height: 38px; width: auto; max-width: 160px; object-fit: contain; display: block;" onerror="this.style.display='none'; document.getElementById('fallback-brand-text').style.display='block';" />
                <div id="fallback-brand-text" class="brand" style="display: none;">Menukit</div>
                <div style="border-left: 2px solid #e2e8f0; padding-left: 14px; display: flex; flex-direction: column; justify-content: center;">
                    <div style="font-size: 13px; font-weight: 800; color: #0f172a; letter-spacing: -0.2px;">Tax Invoice</div>
                    <div style="font-size: 11px; color: #64748b; font-weight: 600;">Official Payment Receipt</div>
                </div>
            </div>
            <div style="text-align: right;">
                <span class="badge">PAID</span>
                <div style="font-size: 12px; color: #94a3b8; margin-top: 6px;">Ref: {data['invoice_number']}</div>
            </div>
        </div>

        <div class="meta-grid">
            <div class="meta-box">
                <label>Billed To</label>
                <span>{data['shop_name']}</span>
                <div style="color: #64748b; font-weight: 500; font-size: 12px;">{data['user_email']}</div>
            </div>
            <div class="meta-box" style="text-align: right;">
                <label>Date & Payment ID</label>
                <span id="invoice-paid-date" data-iso="{data.get('paid_at_iso', '')}">{data['paid_at']}</span>
                <div style="color: #64748b; font-weight: 500; font-size: 12px;">Payment ID: {data['payment_id']}</div>
            </div>
        </div>

        <table>
            <thead>
                <tr>
                    <th>Item Description</th>
                    <th style="text-align: right;">Amount</th>
                </tr>
            </thead>
            <tbody>
                {items_html}
            </tbody>
        </table>

        <div class="totals">
            <div class="totals-row">
                <span>Subtotal (Base)</span>
                <span>₹{data['base_amount']:.2f}</span>
            </div>
            <div class="totals-row">
                <span>Payment Gateway Fee (3% PG + 18% GST)</span>
                <span>₹{data['gateway_fee']:.2f}</span>
            </div>
            <div class="totals-row grand">
                <span>Total Paid</span>
                <span>₹{data['total_amount']:.2f}</span>
            </div>
        </div>

        <button class="print-btn" onclick="window.print()">🖨️ Print / Save Invoice as PDF</button>
    </div>

    <script>
        (function() {{
            try {{
                var dateEl = document.getElementById('invoice-paid-date');
                if (dateEl && dateEl.getAttribute('data-iso')) {{
                    var d = new Date(dateEl.getAttribute('data-iso'));
                    if (!isNaN(d.getTime())) {{
                        dateEl.textContent = d.toLocaleDateString(undefined, {{
                            year: 'numeric',
                            month: 'long',
                            day: 'numeric',
                            hour: '2-digit',
                            minute: '2-digit'
                        }});
                    }}
                }}
            }} catch (e) {{}}
        }})();

        window.addEventListener('load', function() {{
            setTimeout(function() {{
                window.print();
            }}, 300);
        }});
    </script>
</body>
</html>"""
