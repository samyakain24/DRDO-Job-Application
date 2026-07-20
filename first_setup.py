"""
╔══════════════════════════════════════════════════════════════╗
║         DRDO Internship Portal — First-Time Setup           ║
║                                                              ║
║  Run once after cloning the repo:                           ║
║      python first_setup.py                                  ║
╚══════════════════════════════════════════════════════════════╝

What this script does:
  1. Checks Python version (3.10+ required)
  2. Installs pip dependencies from requirements.txt
  3. Asks for your MySQL credentials
  4. Creates the 'drdo_portal' database
  5. Runs schema.sql (tables + seed internship positions)
  6. Creates all demo accounts with correct password hashes
  7. Patches app.py with your DB password so you can run immediately
"""

import sys
import os
import subprocess
import getpass

# ── colour helpers ──────────────────────────────────────────
def green(t):  return f"\033[92m{t}\033[0m"
def red(t):    return f"\033[91m{t}\033[0m"
def yellow(t): return f"\033[93m{t}\033[0m"
def bold(t):   return f"\033[1m{t}\033[0m"
def cyan(t):   return f"\033[96m{t}\033[0m"

def step(n, msg): print(f"\n{cyan(f'[{n}]')} {bold(msg)}")
def ok(msg):      print(f"    {green('✓')} {msg}")
def fail(msg):    print(f"    {red('✗')} {msg}"); sys.exit(1)
def warn(msg):    print(f"    {yellow('⚠')} {msg}")

BANNER = f"""
{cyan('='*62)}
{bold('    DRDO Internship Portal — Automated Setup')}
{cyan('='*62)}
"""

# ── 1. Python version ───────────────────────────────────────
def check_python():
    step(1, "Checking Python version…")
    v = sys.version_info
    if v < (3, 10):
        fail(f"Python 3.10+ required. You have {v.major}.{v.minor}.")
    ok(f"Python {v.major}.{v.minor}.{v.micro}")

# ── 2. Install dependencies ─────────────────────────────────
def install_deps():
    step(2, "Installing Python dependencies…")
    req = os.path.join(os.path.dirname(__file__), "requirements.txt")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", req, "-q"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        warn("pip output:\n" + result.stderr)
        fail("Dependency installation failed.")
    ok("All dependencies installed (flask, mysql-connector-python, werkzeug)")

# ── 3. Collect MySQL credentials ────────────────────────────
def get_credentials():
    step(3, "MySQL credentials")
    print(f"    Enter your MySQL connection details.")
    host = input(f"    Host     [{yellow('localhost')}]: ").strip() or "localhost"
    user = input(f"    User     [{yellow('root')}]: ").strip() or "root"
    password = getpass.getpass(f"    Password (hidden): ")
    db_name  = input(f"    Database [{yellow('drdo_portal')}]: ").strip() or "drdo_portal"
    return host, user, password, db_name

# ── 4 & 5. Create DB + run schema ───────────────────────────
def setup_database(host, user, password, db_name):
    step(4, f"Creating database '{db_name}'…")
    try:
        import mysql.connector
    except ImportError:
        fail("mysql-connector-python not found. Run: pip install mysql-connector-python")

    # Connect without DB to create it
    try:
        conn = mysql.connector.connect(host=host, user=user, password=password)
    except Exception as e:
        fail(f"Cannot connect to MySQL: {e}")

    cur = conn.cursor()
    cur.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    conn.commit()
    ok(f"Database '{db_name}' ready.")

    step(5, "Running schema.sql…")
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as f:
        sql_raw = f.read()

    # Switch to drdo_portal DB
    conn.database = db_name

    # Split and execute statements
    import re
    statements = [s.strip() for s in re.split(r';\s*\n', sql_raw) if s.strip() and not s.strip().startswith("--")]
    skipped = 0
    for stmt in statements:
        stmt = stmt.strip().rstrip(";")
        if not stmt or stmt.upper().startswith("CREATE DATABASE") or stmt.upper().startswith("USE "):
            continue
        try:
            cur.execute(stmt)
        except mysql.connector.Error as e:
            if e.errno in (1050, 1062):  # table exists / dup entry
                skipped += 1
            else:
                warn(f"SQL warning: {e}")
    conn.commit()
    if skipped:
        warn(f"{skipped} statement(s) skipped (already exist — that's fine).")
    ok("Schema applied — tables and seed positions created.")
    return conn, cur

# ── 6. Create demo accounts ─────────────────────────────────
def create_demo_accounts(conn, cur, db_name):
    step(6, "Creating demo accounts…")
    from werkzeug.security import generate_password_hash

    ACCOUNTS = [
        ("DRDO Admin",    "admin@drdo.in",      "Admin@1234",  "admin"),
        ("Dr. Ramesh HR", "hr@drdo.in",          "Hr@1234",     "hr"),
        ("Alice Sharma",  "alice@example.com",   "Alice@1234",  "candidate"),
        ("Bob Verma",     "bob@example.com",     "Bob@1234",    "candidate"),
    ]

    conn.database = db_name
    for name, email, pwd, role in ACCOUNTS:
        hashed = generate_password_hash(pwd)
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE users SET password_hash=%s, is_active=1 WHERE email=%s", (hashed, email))
            ok(f"Updated  {email:30s} ({role})  →  password: {pwd}")
        else:
            cur.execute(
                "INSERT INTO users (full_name, email, password_hash, role) VALUES (%s,%s,%s,%s)",
                (name, email, hashed, role)
            )
            uid = cur.lastrowid
            if role == "candidate":
                cur.execute("INSERT INTO candidate_profiles (user_id) VALUES (%s)", (uid,))
            ok(f"Created  {email:30s} ({role})  →  password: {pwd}")
    conn.commit()

# ── 7. Write DB credentials to .env ─────────────────────────
def write_env(host, user, password, db_name):
    step(7, "Writing your DB credentials to .env…")
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    with open(env_path, "w", encoding="utf-8") as f:
        f.write(f"DB_HOST={host}\n")
        f.write(f"DB_USER={user}\n")
        f.write(f"DB_PASS={password}\n")
        f.write(f"DB_NAME={db_name}\n")
        f.write("SECRET_KEY=dev-secret-change-me\n")
    ok(".env written with your credentials (this file is gitignored).")

# ── Done summary ─────────────────────────────────────────────
def print_summary(db_name):
    print(f"""
{green('='*62)}
{bold('  Setup Complete! Everything is ready.')}
{green('='*62)}

  {bold('Run the portal:')}
      python app.py

  {bold('Open in browser:')}
      http://localhost:5000

  {bold('Demo Login Credentials:')}
  ┌─────────────┬──────────────────────────┬──────────────┐
  │ Role        │ Email                    │ Password     │
  ├─────────────┼──────────────────────────┼──────────────┤
  │ Admin       │ admin@drdo.in            │ Admin@1234   │
  │ HR          │ hr@drdo.in               │ Hr@1234      │
  │ Candidate   │ alice@example.com        │ Alice@1234   │
  │ Candidate   │ bob@example.com          │ Bob@1234     │
  └─────────────┴──────────────────────────┴──────────────┘

  {yellow('Note:')} For production, move DB credentials to environment
        variables and never commit secrets to Git.
""")

# ── Main ─────────────────────────────────────────────────────
if __name__ == "__main__":
    print(BANNER)
    check_python()
    install_deps()
    host, user, password, db_name = get_credentials()
    conn, cur = setup_database(host, user, password, db_name)
    create_demo_accounts(conn, cur, db_name)
    write_env(host, user, password, db_name)
    print_summary(db_name)
