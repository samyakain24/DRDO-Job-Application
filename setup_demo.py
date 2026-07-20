"""
DRDO Portal - Demo Account Setup
Run once after schema.sql to set correct password hashes.

Usage:
    python setup_demo.py

Edit DB_CONFIG below if your MySQL credentials differ.
"""

import os
import mysql.connector
from werkzeug.security import generate_password_hash
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "host":     os.environ.get("DB_HOST", "localhost"),
    "user":     os.environ.get("DB_USER", "root"),
    "password": os.environ.get("DB_PASS", ""),
    "database": os.environ.get("DB_NAME", "drdo_portal"),
}

DEMO_ACCOUNTS = [
    # (email,               password,      role)
    ("admin@drdo.in",      "Admin@1234",  "admin"),
    ("hr@drdo.in",         "Hr@1234",     "hr"),
    ("alice@example.com",  "Alice@1234",  "candidate"),
    ("bob@example.com",    "Bob@1234",    "candidate"),
]

def main():
    try:
        db  = mysql.connector.connect(**DB_CONFIG)
        cur = db.cursor()
        print("Connected to MySQL.\n")
    except Exception as e:
        print(f"ERROR: Could not connect to MySQL.\n{e}")
        return

    for email, password, role in DEMO_ACCOUNTS:
        hashed = generate_password_hash(password)

        # Upsert: update if exists, insert if not
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        row = cur.fetchone()

        if row:
            cur.execute(
                "UPDATE users SET password_hash = %s, role = %s, is_active = 1 WHERE email = %s",
                (hashed, role, email)
            )
            print(f"  [UPDATED]  {email}  ({role})  →  password set to: {password}")
        else:
            # derive a display name from email
            name = email.split("@")[0].replace(".", " ").title()
            cur.execute(
                "INSERT INTO users (full_name, email, password_hash, role) VALUES (%s, %s, %s, %s)",
                (name, email, hashed, role)
            )
            # create empty candidate profile if needed
            if role == "candidate":
                uid = cur.lastrowid
                cur.execute("INSERT INTO candidate_profiles (user_id) VALUES (%s)", (uid,))
            print(f"  [CREATED]  {email}  ({role})  →  password: {password}")

    db.commit()
    cur.close()
    db.close()

    print("\nDone! You can now log in with:")
    print("  Admin     →  admin@drdo.in       /  Admin@1234")
    print("  HR        →  hr@drdo.in          /  Hr@1234")
    print("  Candidate →  alice@example.com   /  Alice@1234")
    print("  Candidate →  bob@example.com     /  Bob@1234")

if __name__ == "__main__":
    main()
