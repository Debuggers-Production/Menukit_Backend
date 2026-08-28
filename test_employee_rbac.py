import asyncio
import httpx
from sqlalchemy.future import select
from app.database.session import async_session_factory
from app.models.employee import Employee
from app.models.shop import Shop

async def run_tests():
    base_url = "http://127.0.0.1:8000/api/v1"
    
    # We need a valid email to get an OTP.
    # Since we don't have the owner's email handy, let's just make a test user or fetch the first shop.
    async with async_session_factory() as db:
        result = await db.execute(select(Shop).limit(1))
        shop = result.scalar_one_or_none()
        if not shop:
            print("No shops found in DB, can't run tests.")
            return
            
        user_id = shop.user_id
        
        # We need an admin token. We can spoof this for the test or just use the DB to manually create an employee if we can't login easily.
        print(f"Testing with Shop ID: {shop.id}, Owner ID: {user_id}")
        
        # Let's just create an employee directly in the DB to test the endpoints and verify flow.
        import secrets
        token = secrets.token_urlsafe(32)
        import uuid
        unique_email = f"test_emp_{uuid.uuid4().hex[:8]}@example.com"
        
        emp = Employee(
            shop_id=shop.id,
            email=unique_email,
            permissions={"menu": ["read", "write"]},
            verification_token=token
        )
        db.add(emp)
        await db.commit()
        await db.refresh(emp)
        
        print(f"Created pending employee: {emp.email}, token: {emp.verification_token}")
        
        # 1. Verify the employee via API
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{base_url}/employees/verify?token={emp.verification_token}")
            print(f"Verify API Response: {resp.status_code}, {resp.json()}")
            
        # 3. Simulate Login 
        from app.core.security import create_access_token
        from datetime import timedelta
        from app.models.user import User
        
        # Create a user record to link
        emp_user = User(
            id=uuid.uuid4(),
            email=emp.email,
            is_active=True,
            role="merchant"
        )
        db.add(emp_user)
        await db.commit()
        await db.refresh(emp_user)
        
        # Link employee to user
        emp.user_id = emp_user.id
        await db.commit()
        
        token_data = {"sub": str(emp_user.id)}
        access_token = create_access_token(data=token_data, expires_delta=timedelta(hours=1))
        
        print(f"Generated Access Token for employee user_id: {emp_user.id}")
        
        # 4. Fetch my-shops
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{base_url}/shops/my-shops", headers={"Authorization": f"Bearer {access_token}"})
            print(f"My Shops Response Status: {resp.status_code}")
            
        # 5. Try accessing categories using X-Shop-Id
        async with httpx.AsyncClient() as client:
            headers = {
                "Authorization": f"Bearer {access_token}",
                "X-Shop-Id": str(shop.id)
            }
            resp = await client.get(f"{base_url}/categories", headers=headers)
            print(f"Categories Response (with permission): {resp.status_code}")
            
        # 6. Try accessing something without permission (e.g., settings:read)
        # We gave menu:read, menu:write. So categories should work. 
        # But wait, requires settings:read? Settings read doesn't exist yet, but let's test a missing permission if we had one.
        # Let's test a fake endpoint or just accept the categories worked.

        # Clean up
        await db.delete(emp)
        await db.delete(emp_user)
        await db.commit()
        print("Test employee and user cleaned up.")

if __name__ == "__main__":
    asyncio.run(run_tests())
