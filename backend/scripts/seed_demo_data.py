"""
seed_demo_data.py — Seed GigShield database with demo users and data.

Run: cd backend && python scripts/seed_demo_data.py

Demo credentials created:
  Admin:        username=admin       password=Admin@GigShield2026
  Hub Manager:  username=hub_manager password=Hub@GigShield2026
  Demo Rider:   email=rider@demo.in  password=Rider@GigShield2026

"""
import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncpg
import bcrypt


def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(12)).decode()


async def seed(database_url: str):
    conn = await asyncpg.connect(database_url)
    print(f"Connected to database")

    # ── Admin user ──────────────────────────────────────────────────────────
    admin_hash = _hash("Admin@GigShield2026")
    await conn.execute("""
        INSERT INTO admin_users (username, password_hash, email, role)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (username) DO UPDATE SET password_hash = EXCLUDED.password_hash
    """, "admin", admin_hash, "admin@gigshield.in", "super_admin")
    print("✅ Admin user:        admin / Admin@GigShield2026")

    # ── Demo hub ────────────────────────────────────────────────────────────
    hub_id = "00000000-0000-0000-0000-000000000001"
    await conn.execute("""
        INSERT INTO hubs (id, name, platform, city, latitude, longitude,
                          h3_index_res9, h3_index_res8, city_multiplier, drainage_index)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        ON CONFLICT (id) DO NOTHING
    """, uuid.UUID(hub_id), "Mumbai Central Hub", "blinkit", "Mumbai",
        19.0760, 72.8777, "8929b1aa3ffffff", "8829b1aa3ffffff", 1.1, 0.4)

    hub2_id = "00000000-0000-0000-0000-000000000002"
    await conn.execute("""
        INSERT INTO hubs (id, name, platform, city, latitude, longitude,
                          h3_index_res9, h3_index_res8, city_multiplier, drainage_index)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        ON CONFLICT (id) DO NOTHING
    """, uuid.UUID(hub2_id), "Bangalore Koramangala Hub", "zepto", "Bangalore",
        12.9352, 77.6245, "8929b37a3ffffff", "8829b37a3ffffff", 1.0, 0.6)
    print("✅ Demo hubs:         Mumbai Central Hub, Bangalore Koramangala Hub")

    # ── Hub manager user ────────────────────────────────────────────────────
    hub_hash = _hash("Hub@GigShield2026")
    await conn.execute("""
        INSERT INTO hub_manager_users (hub_id, username, password_hash, display_name)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (username) DO UPDATE SET password_hash = EXCLUDED.password_hash
    """, uuid.UUID(hub_id), "hub_manager", hub_hash, "Mumbai Hub Manager")
    print("✅ Hub Manager:       hub_manager / Hub@GigShield2026")

    # ── Demo rider ──────────────────────────────────────────────────────────
    from app.core.security import hash_password
    rider_hash = hash_password("Rider@GigShield2026")
    rider_id = await conn.fetchval("""
        INSERT INTO riders (
            name, email, password_hash, phone, platform, city, hub_id,
            declared_income, effective_income, tier, risk_score, risk_profile,
            phone_verified, razorpay_fund_account_id
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
        ON CONFLICT (email) DO UPDATE SET
            password_hash = EXCLUDED.password_hash,
            hub_id = EXCLUDED.hub_id,
            razorpay_fund_account_id = EXCLUDED.razorpay_fund_account_id
        RETURNING id
    """, "Demo Rider", "rider@demo.in", rider_hash, "+919876543210",
        "blinkit", "Mumbai", uuid.UUID(hub_id),
        650.0, 650.0, "B", 35, "low", True, "fa_demo_123456")
    print("✅ Demo Rider:        rider@demo.in / Rider@GigShield2026")

    # ── Demo active policy for demo rider ──────────────────────────────────
    await conn.execute("""
        INSERT INTO policies (
            rider_id, hub_id, plan, status, coverage_pct,
            plan_cap_multiplier, weekly_premium, week_start_date,
            razorpay_fund_account_id
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, CURRENT_DATE, $8)
        ON CONFLICT DO NOTHING
    """, rider_id, uuid.UUID(hub_id), "standard", "active",
        0.70, 5, 55.50, "fa_demo_123456")
    print("✅ Demo Policy:       standard plan, active, ₹55.50/week")

    # ── System config defaults ──────────────────────────────────────────────
    configs = [
        ("global_kill_switch", "off"),
        ("oracle_cycle_interval_min", "15"),
        ("fraud_score_hard_threshold", "0.80"),
        ("vov_reward_amount_inr", "10.00"),
    ]
    for key, val in configs:
        await conn.execute("""
            INSERT INTO system_config (key, value)
            VALUES ($1, $2) ON CONFLICT (key) DO NOTHING
        """, key, val)
    print("✅ System config defaults seeded")

    # ── Train ML model if not already trained ──────────────────────────────
    models_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "models")
    model_path = os.path.join(models_dir, "vulnerability_model.pkl")
    if not os.path.exists(model_path):
        print("\n⚙  Training ML model (first run)...")
        from app.ml.vulnerability_model import train_vulnerability_model
        metrics = train_vulnerability_model()
        if "error" not in metrics:
            print(f"✅ ML Model trained:  AUC-ROC={metrics.get('auc_roc')}, Brier={metrics.get('brier_score')}")
        else:
            print(f"⚠️  ML training failed: {metrics}")
    else:
        print("✅ ML model:          already trained, skipping")

    await conn.close()
    print("\n🎉 Demo seed complete!")
    print("\nLogin credentials:")
    print("  Admin portal:   http://localhost:3000/login/admin")
    print("    username: admin")
    print("    password: Admin@GigShield2026")
    print("  Hub Manager:    http://localhost:3000/login/hub-manager")
    print("    username: hub_manager")
    print("    password: Hub@GigShield2026")
    print("  Rider app:      http://localhost:3000/login/rider")
    print("    email:    rider@demo.in")
    print("    password: Rider@GigShield2026")


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
    db_url = os.getenv("DATABASE_URL", "postgresql://postgres:password@localhost:5432/gigshield")
    asyncio.run(seed(db_url))
