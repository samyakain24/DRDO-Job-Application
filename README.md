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

**3. Set your MySQL password in `app.py`**

Open `app.py` and edit the `DB_CONFIG` block (~line 20):
```python
DB_CONFIG = {
    "host":     "localhost",
    "user":     "root",
    "password": "YOUR_PASSWORD",   # ← change this
    "database": "drdo_portal",
}
```

**4. Create demo accounts**
```bash
python setup_demo.py
```

> `setup_demo.py` connects to MySQL and inserts the four demo users (Admin, HR, and two Candidates) with correctly hashed passwords. If a user already exists, it just updates the password. Edit `DB_CONFIG` at the top of that file to match your credentials before running.

---

## Run the Portal

```bash
python app.py
```

Open **http://localhost:5000**

---

## Demo Login Credentials

| Role      | Email                | Password   |
|-----------|----------------------|------------|
| Admin     | admin@drdo.in        | Admin@1234 |
| HR        | hr@drdo.in           | Hr@1234    |
| Candidate | alice@example.com    | Alice@1234 |
| Candidate | bob@example.com      | Bob@1234   |

New candidates can also self-register at `/register`.
