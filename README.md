# DRDO Internship Portal — Setup Guide

---

## Requirements

- Python 3.10+
- MySQL 8.0+

---

## Setup

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
