"""MenuKit Standalone Real-Time Dynamic Pricing Engine.

Calculates country-specific, currency-converted, and psychologically rounded pricing
from the Master India (INR) base price. Completely decoupled from payment providers.
"""

import math
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from app.services.fx_service import fx_service


@dataclass
class CountryConfig:
    code: str
    name: str
    currency: str
    symbol: str
    flag: str
    multiplier: float
    rounding_rule: str  # "point_99", "integer", "point_49_99"


# Supported Country Matrix (Internal multipliers are never exposed to customers directly)
COUNTRIES_CONFIG: Dict[str, CountryConfig] = {
    "IN": CountryConfig(
        code="IN",
        name="India",
        currency="INR",
        symbol="₹",
        flag="🇮🇳",
        multiplier=1.0,
        rounding_rule="integer"
    ),
    "US": CountryConfig(
        code="US",
        name="United States",
        currency="USD",
        symbol="$",
        flag="🇺🇸",
        multiplier=2.0,
        rounding_rule="point_99"
    ),
    "GB": CountryConfig(
        code="GB",
        name="United Kingdom",
        currency="GBP",
        symbol="£",
        flag="🇬🇧",
        multiplier=2.0,
        rounding_rule="point_99"
    ),
    "AU": CountryConfig(
        code="AU",
        name="Australia",
        currency="AUD",
        symbol="A$",
        flag="🇦🇺",
        multiplier=2.0,
        rounding_rule="point_99"
    ),
    "CA": CountryConfig(
        code="CA",
        name="Canada",
        currency="CAD",
        symbol="C$",
        flag="🇨🇦",
        multiplier=2.0,
        rounding_rule="point_99"
    ),
    "EU": CountryConfig(
        code="EU",
        name="Europe",
        currency="EUR",
        symbol="€",
        flag="🇪🇺",
        multiplier=2.0,
        rounding_rule="point_99"
    ),
    "OTHER": CountryConfig(
        code="OTHER",
        name="International / Other",
        currency="USD",
        symbol="$",
        flag="🌎",
        multiplier=2.0,
        rounding_rule="point_99"
    )
}

# Master / Base Prices in INR (Monthly)
BASE_INR_PRICES = {
    "all_access": 399.0,
    "modules": {
        "online-orders": 129.0,
        "new-member": 99.0,
        "member-count": 99.0,
        "member-details": 129.0,
        "search-data": 69.0,
        "custom-theme": 69.0,
        "analytics-advanced": 129.0,
        "analytics-advanced-filters": 59.0,
        "analytics-customer-insights": 59.0,
        "hide-discovery-badge": 49.0,
    }
}

# Module Definitions & Metadata
MODULE_METADATA = [
    {
        "id": "online-orders",
        "name": "Online Visibility & Orders Accept",
        "category": "Online Ordering",
        "description": "Accept online delivery & takeaway orders directly with live online menu visibility.",
        "icon": "Globe"
    },
    {
        "id": "member-count",
        "name": "New Member Count",
        "category": "Relationship Marketing",
        "description": "Track how many new members/customers join every month seamlessly.",
        "icon": "Users"
    },
    {
        "id": "member-details",
        "name": "New Member + Details",
        "category": "Relationship Marketing",
        "description": "Store and manage deep customer information along with member growth metrics.",
        "icon": "Users"
    },
    {
        "id": "search-data",
        "name": "Customer Search Data",
        "category": "Marketing",
        "description": "Access search analytics and real-time customer interest insights.",
        "icon": "Search"
    },
    {
        "id": "custom-theme",
        "name": "Custom Theme Studio",
        "category": "Branding",
        "description": "Customize colors, logos, and custom branding of your digital menu.",
        "icon": "Palette"
    },
    {
        "id": "analytics-advanced",
        "name": "Advanced Analytics",
        "category": "Analytics",
        "description": "Unlock 7-day, 30-day, Custom Date range filters, and detailed customer insights reports.",
        "icon": "BarChart3"
    },
    {
        "id": "analytics-advanced-filters",
        "name": "Advanced Analytics Filters",
        "category": "Analytics",
        "description": "Unlock 7-day, 30-day, and Custom Date range filters for your dashboard.",
        "icon": "BarChart3"
    },
    {
        "id": "analytics-customer-insights",
        "name": "Customer Insights Report",
        "category": "Analytics",
        "description": "Access detailed reports on customer views and repeat visits.",
        "icon": "BarChart3"
    },
    {
        "id": "hide-discovery-badge",
        "name": "Featured Discovery (No Menu Badge)",
        "category": "Discovery",
        "description": "Keep your shop discoverable on the public map & search while removing the outward Discover label from your customer menu.",
        "icon": "MapPin"
    }
]


class PricingEngine:
    """Core pricing calculator for global multi-currency plans."""

    @classmethod
    def get_country_config(cls, country_code: Optional[str]) -> CountryConfig:
        """Resolve country code to CountryConfig with fallback to OTHER or IN."""
        if not country_code:
            return COUNTRIES_CONFIG["IN"]
        code = country_code.upper().strip()
        return COUNTRIES_CONFIG.get(code, COUNTRIES_CONFIG["OTHER"])

    @classmethod
    def apply_psychological_rounding(cls, raw_price: float, rule: str) -> float:
        """
        Apply currency-specific psychological rounding.
        - "point_99": $8.73 -> $8.99, $9.21 -> $9.99, £6.84 -> £6.99, A$15.27 -> A$15.99
        - "integer": ₹399 -> ₹399, ₹129 -> ₹129, ₹798 -> ₹798
        """
        if raw_price <= 0:
            return 0.0

        if rule == "integer":
            return float(round(raw_price))

        if rule == "point_99":
            # If already ending near .99 (e.g. 8.99)
            whole_part = math.floor(raw_price)
            decimal_part = raw_price - whole_part
            if decimal_part == 0:
                # e.g. 8.0 -> 7.99 or 8.99
                return round(whole_part - 0.01 if whole_part > 1 else 0.99, 2)
            
            # Use ceil minus 0.01: 8.73 -> ceil(8.73)=9 -> 8.99; 9.21 -> ceil(9.21)=10 -> 9.99
            rounded = math.ceil(raw_price) - 0.01
            return round(rounded, 2)

        return round(raw_price, 2)

    @classmethod
    async def calculate_price(
        cls,
        base_inr_price: float,
        country_code: str,
        billing_cycle: str = "monthly"
    ) -> Dict[str, Any]:
        """
        Calculate final customer-facing price for an INR base amount:
        1. International Target INR = India Base Price * Country Multiplier
        2. Local Currency Price = International Target INR * FX Rate (INR -> Local)
        3. Round to clean psychological price
        """
        config = cls.get_country_config(country_code)
        
        # 1. Target INR
        target_inr = base_inr_price * config.multiplier

        # 2. FX Conversion
        fx_rate = await fx_service.get_rate_for_currency(config.currency)
        raw_local_monthly = target_inr * fx_rate

        # 3. Monthly Rounded Price
        monthly_price = cls.apply_psychological_rounding(raw_local_monthly, config.rounding_rule)

        # 4. Yearly calculation (10x monthly base price - 2 months free!)
        if config.currency == "INR":
            yearly_raw = target_inr * 10.0
            yearly_price = float(round(yearly_raw))
        else:
            yearly_raw = (target_inr * 10.0) * fx_rate
            yearly_price = cls.apply_psychological_rounding(yearly_raw, config.rounding_rule)

        # Selected interval price
        selected_price = yearly_price if billing_cycle == "yearly" else monthly_price

        return {
            "country_code": config.code,
            "currency": config.currency,
            "currency_symbol": config.symbol,
            "monthly_price": monthly_price,
            "yearly_price": yearly_price,
            "selected_price": selected_price,
            "billing_cycle": billing_cycle,
            "fx_rate": fx_rate,
            "base_inr": base_inr_price,
            "target_inr": target_inr,
        }

    @classmethod
    async def get_pricing_catalog(
        cls,
        country_code: str,
        billing_cycle: str = "monthly"
    ) -> Dict[str, Any]:
        """Get full localized pricing catalog for the pricing page & subscription marketplace."""
        config = cls.get_country_config(country_code)
        
        # All Access Plan
        all_access_calc = await cls.calculate_price(
            BASE_INR_PRICES["all_access"],
            config.code,
            billing_cycle
        )

        # Addon Modules
        modules = []
        for mod_meta in MODULE_METADATA:
            mod_id = mod_meta["id"]
            base_inr = BASE_INR_PRICES["modules"].get(mod_id, 99.0)
            calc = await cls.calculate_price(base_inr, config.code, billing_cycle)
            modules.append({
                **mod_meta,
                "price": calc["selected_price"],
                "monthly_price": calc["monthly_price"],
                "yearly_price": calc["yearly_price"],
                "currency": config.currency,
                "currency_symbol": config.symbol,
            })

        # List of supported countries for frontend selector
        country_list = [
            {
                "code": c.code,
                "name": c.name,
                "currency": c.currency,
                "symbol": c.symbol,
                "flag": c.flag
            }
            for c in COUNTRIES_CONFIG.values()
        ]

        return {
            "country": {
                "code": config.code,
                "name": config.name,
                "currency": config.currency,
                "currency_symbol": config.symbol,
                "flag": config.flag
            },
            "billing_cycle": billing_cycle,
            "all_access": {
                "name": "All-Access VIP Pass",
                "price": all_access_calc["selected_price"],
                "monthly_price": all_access_calc["monthly_price"],
                "yearly_price": all_access_calc["yearly_price"],
                "currency": config.currency,
                "currency_symbol": config.symbol,
                "description": "Unlock everything — all current and future modules included without restrictions."
            },
            "modules": modules,
            "supported_countries": country_list
        }

    @classmethod
    async def calculate_order_total(
        cls,
        is_all_access: bool,
        selected_modules: List[str],
        country_code: str,
        billing_cycle: str = "monthly"
    ) -> Dict[str, Any]:
        """
        Secure backend single source of truth order total calculation:
        Computes base amount, PG fee (3%), GST (18% on PG fee for INR or standard fee),
        and final total in customer currency + INR equivalent for payment gateway.
        """
        config = cls.get_country_config(country_code)
        
        base_subtotal = 0.0
        if is_all_access:
            calc = await cls.calculate_price(BASE_INR_PRICES["all_access"], config.code, billing_cycle)
            base_subtotal = calc["selected_price"]
        else:
            for mod_id in selected_modules:
                base_inr = BASE_INR_PRICES["modules"].get(mod_id, 99.0)
                calc = await cls.calculate_price(base_inr, config.code, billing_cycle)
                base_subtotal += calc["selected_price"]

        base_subtotal = round(base_subtotal, 2)

        # Payment Gateway Fee (3%) + GST (18% on PG fee)
        pg_fee = round(base_subtotal * 0.03, 2)
        gst_on_fee = round(pg_fee * 0.18, 2)
        final_total = round(base_subtotal + pg_fee + gst_on_fee, 2)

        # Also compute equivalent in INR for gateway settlement / fallback
        fx_rate = await fx_service.get_rate_for_currency(config.currency)
        if config.currency == "INR" or fx_rate == 0:
            inr_final_total = final_total
        else:
            # local_amount / fx_rate = inr_amount
            inr_final_total = round(final_total / fx_rate, 2)

        # Gateway subunit amount:
        # For INR: amount in paise (1 INR = 100 paise)
        # For USD, EUR, GBP, AUD, CAD: amount in cents / pence (1 unit = 100 subunits)
        amount_subunits = int(round(final_total * 100))

        return {
            "country_code": config.code,
            "currency": config.currency,
            "currency_symbol": config.symbol,
            "base_subtotal": base_subtotal,
            "pg_fee": pg_fee,
            "gst_on_fee": gst_on_fee,
            "final_total": final_total,
            "inr_equivalent": inr_final_total,
            "amount_subunits": amount_subunits,
            "fx_rate": fx_rate,
            "billing_cycle": billing_cycle,
            "is_all_access": is_all_access,
            "selected_modules": selected_modules
        }


pricing_engine = PricingEngine()
