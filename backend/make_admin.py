import asyncio
import sys
import asyncpg
from core.config import DATABASE_URL

async def make_admin(email: str):
    print(f"Connecting to DB to promote: {email}")
    conn = await asyncpg.connect(DATABASE_URL)
    
    try:
        # Check if user exists
        user = await conn.fetchrow("SELECT id, email FROM users WHERE email = $1", email)
        if not user:
            print(f"ERROR: User with email '{email}' not found.")
            # List some users to help
            users = await conn.fetch("SELECT email FROM users LIMIT 5")
            if users:
                print("Available users in DB:")
                for u in users:
                    print(f" - {u['email']}")
            return

        user_id = user['id']
        scopes = [
            "admin:read",
            "admin:users",
            "admin:logs",
            "admin:metrics"
        ]
        
        await conn.execute("""
            UPDATE users 
            SET role = 'admin', scopes = $1 
            WHERE id = $2
        """, scopes, user_id)
        
        print(f"SUCCESS: User {email} (ID: {user_id}) is now an ADMIN with full scopes.")
        print("Please log out and log back in on the frontend to update your token.")

    except Exception as e:
        print(f"Promotion failed: {e}")
    finally:
        await conn.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python make_admin.py <email>")
        sys.exit(1)
        
    email_arg = sys.argv[1]
    asyncio.run(make_admin(email_arg))
