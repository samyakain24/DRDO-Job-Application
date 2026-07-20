# DRDO Internship Portal — Setup Guide

A Flask + MySQL internship application portal with three roles (`admin`, `hr`, `candidate`) and an AI resume↔job-role matcher.

---

## Quick Start

Assumes Python 3.10+, MySQL 8.0+, and Git are already installed.

**1. Clone and enter the repo**
```bash
git clone https://github.com/samyakain24/DRDO-Job-Application.git
cd DRDO-Job-Application
```

**2. Create and activate a virtual environment**
```bash
python -m venv venv
```
- Windows (PowerShell): `venv\Scripts\activate`
- Mac/Linux: `source venv/bin/activate`

**3. Start MySQL**
- Windows (PowerShell as Administrator): `net start MySQL80` (or start it via `services.msc`)
- Mac: `sudo /usr/local/mysql/support-files/mysql.server start` (or `brew services start mysql`)

**4. Run the automated setup**
```bash
python first_setup.py
```
This installs dependencies, creates the `drdo_portal` database, applies the schema, loads seed data, creates the demo accounts, and writes your DB credentials to a local `.env` file.

**5. Run the app**
```bash
python app.py
```

**6. Open it**

**http://localhost:5050**

---

## Requirements

- Python 3.10+
- MySQL 8.0+

---

## Setup (detailed)

### Option A — Automatic (Recommended)

Run the setup script. It installs dependencies, creates the database, runs the schema, and creates demo accounts in one go.

```bash
python first_setup.py
```

It will ask for your MySQL host, username, and password interactively. Once done, skip to **Run the Portal** below.

---

### Option B — Manual

**1. Install dependencies**
```bash
pip install -r requirements.txt
```

**2. Create the database and tables**
```bash
mysql -u root -p < schema.sql
```
> **Windows PowerShell users:** PowerShell doesn't support `<` for input redirection. Wrap the command instead:
> ```powershell
> cmd /c "mysql -u root -p < schema.sql"
> ```

`schema.sql` already seeds the four demo accounts with working password hashes, so login works immediately after this step — `setup_demo.py` is only needed later if you want to reset a demo password.

**3. Create a `.env` file**

Copy `.env.example` to `.env` and fill in your real MySQL password:
```bash
cp .env.example .env
```
```env
DB_HOST=localhost
DB_USER=root
DB_PASS=YOUR_PASSWORD
DB_NAME=drdo_portal
SECRET_KEY=change-me-in-production
```
`.env` is gitignored — never commit real credentials to `app.py` or to git.

---

## Run the Portal

```bash
python app.py
```

Open **http://localhost:5050**

---

## Demo Login Credentials

| Role      | Email                | Password   |
|-----------|----------------------|------------|
| Admin     | admin@drdo.in        | Admin@1234 |
| HR        | hr@drdo.in           | Hr@1234    |
| Candidate | alice@example.com    | Alice@1234 |
| Candidate | bob@example.com      | Bob@1234   |

New candidates can also self-register at `/register`.

---

## Troubleshooting

- **`Access denied for user 'root'@'localhost'`** — the password in `.env` (`DB_PASS`) doesn't match your actual MySQL root password. Verify it with `mysql -u root -p -e "SELECT 1;"` and update `.env` to match.
- **`Can't connect to MySQL server` / socket error** — MySQL isn't running. See step 3 above.
- **Nothing at `localhost:5050`** — check the app actually started without errors in the terminal; the port is `5050`, not the Flask default of `5000`.
- **PowerShell says an operator is "reserved for future use"** — this happens with `<`, `&`, and a few other shell operators that PowerShell doesn't support the way bash does. Prefer running the Python scripts (`first_setup.py`, `app.py`) directly rather than piping/redirecting into the `mysql` CLI by hand.
