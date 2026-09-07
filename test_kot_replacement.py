"""
Verification test for KOT item cancellation and replacement logic using in-memory SQLite.
"""
import asyncio
import uuid
import sys
sys.stdout.reconfigure(encoding='utf-8')

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from app.database.base import Base
import app.models  # load models
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB

from app.models.order import Order, OrderItem
from app.services.order_service import OrderService
from app.schemas.order import OrderItemReplace

@compiles(JSONB, 'sqlite')
def compile_jsonb_sqlite(type_, compiler, **kw):
    return 'JSON'

async def run_test():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    
    # Create only Order and OrderItem tables for test
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn, tables=[Order.__table__, OrderItem.__table__]
            )
        )

    async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        service = OrderService(session)
        
        shop_id = uuid.uuid4()
        order_id = uuid.uuid4()
        item1_id = uuid.uuid4()
        item2_id = uuid.uuid4()
        menu_item1_id = uuid.uuid4()
        menu_item2_id = uuid.uuid4()
        menu_item_replace_id = uuid.uuid4()

        order = Order(
            id=order_id,
            shop_id=shop_id,
            customer_name="Ramesh Kumar",
            customer_phone="9876543210",
            order_type="dine_in",
            table_number="T-05",
            order_status="PREPARING",
            payment_status="pending",
            payment_method="cash",
            total_amount=350.0,
            version=1
        )
        session.add(order)
        await session.flush()

        item1 = OrderItem(
            id=item1_id,
            order_id=order_id,
            menu_item_id=menu_item1_id,
            name="Chicken Biryani",
            quantity=2,
            price=100.0,
            is_completed=False,
            is_cancelled=False
        )
        item2 = OrderItem(
            id=item2_id,
            order_id=order_id,
            menu_item_id=menu_item2_id,
            name="Mutton Sukka",
            quantity=1,
            price=150.0,
            is_completed=False,
            is_cancelled=False
        )
        session.add_all([item1, item2])
        await session.commit()

        print(f"[Step 1] Order created with total_amount = {order.total_amount}")
        assert float(order.total_amount) == 350.0

        # Step 2: Cancel item 2 (Mutton Sukka, 150)
        print("[Step 2] Testing item cancellation with custom reason...")
        updated_order = await service.toggle_order_item_cancel(
            order_id, item2_id, shop_id, reason="Guest decided not to have mutton"
        )
        await session.commit()
        await session.refresh(order)

        cancelled_item = next(it for it in updated_order.items if it.id == item2_id)
        assert cancelled_item.is_cancelled == True
        assert cancelled_item.cancellation_reason == "Guest decided not to have mutton"
        print(f"   ✓ Item 2 cancelled: {cancelled_item.name} | Reason: {cancelled_item.cancellation_reason}")
        print(f"   ✓ Order total_amount after cancellation: {updated_order.total_amount} (Expected 200.0)")
        assert float(updated_order.total_amount) == 200.0

        # Step 3: Replace item 1 (Chicken Biryani, 2x100 = 200) with Special Fried Rice (2x80 = 160)
        print("[Step 3] Testing atomic item replacement...")
        replace_data = OrderItemReplace(
            new_menu_item_id=menu_item_replace_id,
            name="Special Fried Rice",
            quantity=2,
            price=80.0,
            reason="Customer allergic to biryani masala"
        )
        replaced_order = await service.replace_order_item(
            order_id, item1_id, shop_id, replace_data
        )
        await session.commit()
        await session.refresh(order)

        orig_item = next(it for it in replaced_order.items if it.id == item1_id)
        assert orig_item.is_cancelled == True
        assert "Special Fried Rice" in orig_item.cancellation_reason
        print(f"   ✓ Original Item 1 cancelled: {orig_item.name} | Reason: {orig_item.cancellation_reason}")
        
        # Check that replacement item was added
        new_item = next((it for it in replaced_order.items if it.name == "Special Fried Rice"), None)
        assert new_item is not None
        assert new_item.quantity == 2
        assert float(new_item.price) == 80.0
        print(f"   ✓ Replacement Item added: {new_item.name} | Qty: {new_item.quantity} | Price: {new_item.price}")
        print(f"   ✓ Order total_amount after replacement: {replaced_order.total_amount} (Expected 160.0)")
        assert float(replaced_order.total_amount) == 160.0

        # Step 4: Restore item 2 (Mutton Sukka, 150)
        print("[Step 4] Testing item restoration...")
        restored_order = await service.toggle_order_item_cancel(order_id, item2_id, shop_id)
        await session.commit()
        await session.refresh(order)

        restored_item = next(it for it in restored_order.items if it.id == item2_id)
        assert restored_item.is_cancelled == False
        assert restored_item.cancellation_reason is None
        print(f"   ✓ Item 2 restored: is_cancelled={restored_item.is_cancelled}")
        print(f"   ✓ Order total_amount after restoration: {restored_order.total_amount} (Expected 310.0)")
        assert float(restored_order.total_amount) == 310.0

        print("\n========================================================")
        print("  ALL BACKEND KOT LOGIC TESTS PASSED SUCCESSFULLY! ")
        print("========================================================")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(run_test())
