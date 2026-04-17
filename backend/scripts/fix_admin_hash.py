# Run once: python scripts/fix_admin_hash.py
# Copy the SQL output → paste into Supabase SQL Editor → Run

import bcrypt


if __name__ == "__main__":
    new_hash = bcrypt.hashpw(b"GigShield@Admin123", bcrypt.gensalt(12)).decode()
    print(new_hash)
    print(f"UPDATE admin_users SET password_hash = '{new_hash}' WHERE username = 'admin';")
