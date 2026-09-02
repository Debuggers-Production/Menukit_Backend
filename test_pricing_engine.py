import sys
import asyncio
sys.stdout.reconfigure(encoding='utf-8')
from app.services.pricing_engine import pricing_engine
from app.services.fx_service import fx_service

async def main():
    rates = await fx_service.get_rates()
    print("FX Rates sample:", {k: rates.get(k) for k in ['USD', 'GBP', 'AUD', 'CAD', 'EUR']})
    
    for country in ['IN', 'US', 'GB', 'AU', 'CA', 'OTHER']:
        catalog = await pricing_engine.get_pricing_catalog(country, 'monthly')
        all_acc = catalog['all_access']
        c_curr = catalog['country']['currency']
        c_sym = catalog['country']['currency_symbol']
        c_flag = catalog['country']['flag']
        print(f"{c_flag} {country} ({c_curr} {c_sym}): All-Access = {c_sym}{all_acc['price']}/mo, Yearly = {c_sym}{all_acc['yearly_price']}/yr")
        for mod in catalog['modules'][:3]:
            print(f"   -> {mod['name']}: {mod['currency_symbol']}{mod['price']}/mo")
        
    order_us = await pricing_engine.calculate_order_total(True, [], 'US', 'monthly')
    print("\nUS Order Calculation:", order_us)

    order_in = await pricing_engine.calculate_order_total(True, [], 'IN', 'monthly')
    print("\nIN Order Calculation:", order_in)

if __name__ == "__main__":
    asyncio.run(main())
