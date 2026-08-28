import asyncio
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, update
from app.database.session import async_session_factory
from app.models.subscription import Subscription

async def reset_trials():
    print("Connecting to database and updating subscriptions...")
    
    # 30 days from now
    new_end_date = datetime.now(timezone.utc) + timedelta(days=30)
    
    async with async_session_factory() as db:
        stmt = (
            update(Subscription)
            .values(
                is_trial=True,
                is_active=True,
                is_all_access=True,
                current_period_end=new_end_date
            )
            .returning(Subscription.id)
        )
        
        result = await db.execute(stmt)
        updated_ids = result.scalars().all()
        await db.commit()
        
        print(f"Successfully updated {len(updated_ids)} subscriptions to have a 30-day free trial.")
        print(f"New trial end date: {new_end_date.strftime('%Y-%m-%d %H:%M:%S UTC')}")

if __name__ == "__main__":
    asyncio.run(reset_trials())
