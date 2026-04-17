#!/usr/bin/env python3
"""
scripts/seed_db.py — Seed hubs, system_config, admin user.
Run: python scripts/seed_db.py
No Docker required — connects directly via DATABASE_URL.
"""
import asyncio, sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import asyncpg
from app.config import get_settings
from app.core.security import hash_password
from app.utils.h3_utils import latlng_to_h3

settings = get_settings()

HUBS = [
    {"name":"Zepto Andheri West",   "platform":"zepto",    "city":"Mumbai",    "lat":19.1136,"lng":72.8697,"mult":1.35,"drain":0.3,"cap":150},
    {"name":"Blinkit Bandra Hub",   "platform":"blinkit",  "city":"Mumbai",    "lat":19.0596,"lng":72.8295,"mult":1.35,"drain":0.4,"cap":120},
    {"name":"Instamart Powai Hub",  "platform":"instamart","city":"Mumbai",    "lat":19.1176,"lng":72.9060,"mult":1.35,"drain":0.5,"cap":100},
    {"name":"Zepto Connaught Place","platform":"zepto",    "city":"Delhi",     "lat":28.6315,"lng":77.2167,"mult":1.28,"drain":0.5,"cap":130},
    {"name":"Blinkit Lajpat Nagar", "platform":"blinkit",  "city":"Delhi",     "lat":28.5677,"lng":77.2432,"mult":1.28,"drain":0.5,"cap":110},
    {"name":"Zepto Indiranagar",    "platform":"zepto",    "city":"Bangalore", "lat":12.9784,"lng":77.6408,"mult":1.15,"drain":0.6,"cap":100},
    {"name":"Blinkit Koramangala",  "platform":"blinkit",  "city":"Bangalore", "lat":12.9352,"lng":77.6245,"mult":1.15,"drain":0.6,"cap":90},
    {"name":"Zepto T. Nagar",       "platform":"zepto",    "city":"Chennai",   "lat":13.0418,"lng":80.2341,"mult":1.08,"drain":0.4,"cap":80},
    {"name":"Blinkit Koregaon Park","platform":"blinkit",  "city":"Pune",      "lat":18.5362,"lng":73.8938,"mult":1.05,"drain":0.6,"cap":70},
]

SYSTEM_CONFIG = [
    ("global_kill_switch",      "off"),
    ("oracle_threshold",        "0.65"),
    ("auto_clear_fs_threshold", "0.40"),
    ("hard_flag_fs_threshold",  "0.70"),
    ("lambda_floor",            "1.0"),
    ("capital_reserves",        "500000"),
    ("reserve_buffer_inr",      "500000"),
    ("p_base_margin_pct",       "0.25"),
    ("liquidity_mode",          "normal"),
]


async def seed():
    print(f"Connecting to: {settings.database_url[:40]}...")
    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=3)

    async with pool.acquire() as conn:
        print("\n── Seeding hubs ─────────────────────────────────")
        for h in HUBS:
            h3_res9 = latlng_to_h3(h["lat"], h["lng"], 9)
            h3_res8 = latlng_to_h3(h["lat"], h["lng"], 8)
            hub_id  = await conn.fetchval("""
                INSERT INTO hubs(name,platform,city,latitude,longitude,
                    h3_index_res9,h3_index_res8,city_multiplier,drainage_index,capacity,rain_threshold_mm)
                VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,35.0)
                ON CONFLICT DO NOTHING RETURNING id
            """, h["name"],h["platform"],h["city"],h["lat"],h["lng"],h3_res9,h3_res8,h["mult"],h["drain"],h["cap"])

            # Seed zone_risk_cache for this hub
            await conn.execute("""
                INSERT INTO zone_risk_cache(h3_index,vulnerability_idx,cold_start_mode,active_policies,lambda_surge)
                VALUES($1,0.50,true,0,1.0) ON CONFLICT DO NOTHING
            """, h3_res9)

            status = "✓ created" if hub_id else "- exists"
            print(f"  {status}: {h['name']} ({h['city']}) {h3_res9}")

        print("\n── Seeding system_config ────────────────────────")
        for key, val in SYSTEM_CONFIG:
            await conn.execute(
                "INSERT INTO system_config(key,value) VALUES($1,$2) ON CONFLICT(key) DO NOTHING",
                key, val,
            )
        print(f"  ✓ {len(SYSTEM_CONFIG)} config entries")

        print("\n── Seeding plan_config ──────────────────────────")
        plans = [
            ("basic",    ["rain","bandh","platform_down"],                       29.0, 3),
            ("standard", ["rain","bandh","platform_down","flood","aqi"],          49.0, 5),
            ("pro",      ["rain","bandh","platform_down","flood","aqi","heat"],   79.0, 7),
        ]
        for plan, triggers, prem, cap in plans:
            await conn.execute(
                "INSERT INTO plan_config(plan,covered_triggers,base_premium,cap_multiplier) VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING",
                plan, triggers, prem, cap,
            )
        print(f"  ✓ {len(plans)} plans")

        print("\n── Seeding admin user ───────────────────────────")
        # BLOCKER #10 FIX: Standardized to match seed_demo_data.py and README.md
        # Single canonical password across all seed scripts: Admin@GigShield2026
        admin_password = "Admin@GigShield2026"
        aid = await conn.fetchval("""
            INSERT INTO admin_users(username,password_hash,email)
            VALUES('admin',$1,'admin@gigshield.in')
            ON CONFLICT DO NOTHING RETURNING id
        """, hash_password(admin_password))
        if aid:
            print(f"  ✓ Admin user created")
            print(f"    Username: admin")
            print(f"    Password: {admin_password}")
        else:
            print("  - Admin user already exists")

    await pool.close()
    print("\n✅ Seed complete!\n")
    print("Next steps:")
    print("  uvicorn app.main:app --reload --port 8000")
    print("  celery -A app.workers.celery_app worker --loglevel=info")


if __name__ == "__main__":
    asyncio.run(seed())
