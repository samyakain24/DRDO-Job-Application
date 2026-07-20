# Edits.md

Notes on this codebase's structure and conventions, for anyone working in this repository.

## What this is

A Flask + MySQL internship application portal (DRDO Internship Portal) with three roles — `admin`, `hr`, `candidate` — plus a bundled scikit-learn resume↔job-role matcher that scores an uploaded resume PDF against 5 trained job-role categories, and a per-position applicant ranking feature that scores each applicant's resume against one specific internship posting's own text.

## Setup & running

```bash
python first_setup.py          # one-time: installs deps, creates DB, runs schema.sql, creates demo accounts, writes .env
python app.py                  # runs the app on http://localhost:5050 (debug=True)
```

Manual setup (if not using `first_setup.py`):
```bash
pip install -r requirements.txt
mysql -u root -p < schema.sql          # creates drdo_portal DB + tables + seed positions (demo accounts already work after this)
cp .env.example .env                   # then fill in your real DB_PASS
```

DB credentials and `SECRET_KEY` are read from a `.env` file (loaded via `python-dotenv`; see `.env.example`) into env vars (`DB_HOST`, `DB_USER`, `DB_PASS`, `DB_NAME`, `SECRET_KEY`) consumed by `app.py`'s `DB_CONFIG`. `.env` is gitignored — never hardcode real credentials in `app.py` itself.

There is no test suite, linter, or build step configured in this repo.

### Demo accounts
| Role | Email | Password |
|------|-------|----------|
| Admin | admin@drdo.in | Admin@1234 |
| HR | hr@drdo.in | Hr@1234 |
| Candidate | alice@example.com | Alice@1234 |
| Candidate | bob@example.com | Bob@1234 |

`schema.sql`'s seed data inserts the two demo candidates into `users` but also creates a matching `candidate_profiles` row for each (`INSERT INTO candidate_profiles (user_id) VALUES ...`) — without that row, `candidate_profile()`'s `UPDATE ... WHERE user_id=%s` silently affects 0 rows and profile edits appear to save but don't. Any candidate created outside `schema.sql`/`setup_demo.py` (e.g. inserted directly via SQL) needs the same paired insert; only the `/register` route and `setup_demo.py` do this automatically.

### Migrating an existing DB
If `drdo_portal` was created before the resume-matching feature existed, run `mysql -u root -p drdo_portal < migrate_resume_match.sql` to add the missing `candidate_profiles` columns (safe to re-run; duplicate-column errors are expected/ignored).

If it was created before the per-position applicant ranking feature existed, also run `mysql -u root -p drdo_portal < migrate_position_match.sql` to add `candidate_profiles.resume_text` (same safe-to-re-run behavior).

Symptom if you skip either migration: `mysql.connector.errors.ProgrammingError: Unknown column '...'` the first time a route touches the missing column.

## Architecture

**Single-file Flask app** (`app.py`, ~600 lines) — all routes, DB access, and the resume-matcher integration live here. No blueprints/models module; routes are grouped by role with comment-banner section headers (public / candidate / hr / admin / profile / Jinja filters).

- **DB access**: no ORM. `query(sql, params, one=False, commit=False)` is the single helper used everywhere — opens a per-request `mysql.connector` connection stashed on Flask's `g`, executes raw parameterized SQL, and either commits+returns `lastrowid` or returns fetched dict rows. All handlers call this helper directly.
- **Auth**: session-based (`session["user_id"/"user_name"/"role"]`). Two decorators compose on routes: `@login_required` and `@role_required("admin", "hr", ...)`.
- **DB schema** (`schema.sql`): `users` (role enum) → `candidate_profiles` (1:1, includes resume match columns plus `resume_text` — cached plain-text extraction of the uploaded PDF, used for on-demand per-position matching) / `internship_positions` (created by HR) → `applications` (candidate × position, unique pair, status enum) → `application_history` (audit trail of status changes, one row per transition).
- **Templates**: Jinja2 in `templates/`, all extending `base.html`, named `<role>_<page>.html`. Two custom Jinja filters registered in `app.py`: `status_color` (maps application status → Bootstrap color class) and `datefmt`.

### Resume matcher (`resume_matcher/`)

This is a **plain module folder, not a Python package** — its files import each other with bare names (`from match import score_resume`, `from pdf_utils import extract_text_from_pdf`), so `app.py` adds `resume_matcher/` to `sys.path` at startup rather than importing it as `resume_matcher.match`. Keep intra-folder imports bare, not `resume_matcher.x`.

- `pdf_utils.py` — `extract_text_from_pdf`: pulls + lightly cleans text from a PDF.
- `dataset.py` — walks a directory of `<role> jobs/*.pdf` folders to build labeled training examples (role name = folder name).
- `train_model.py` — full training pipeline: TF-IDF → TruncatedSVD(LSA) → LogisticRegression, cross-validated. Saves vectorizer + SVD + normalizer + classifier + per-posting vectors to `model.joblib`. Run via `python train_model.py --data-dir "../.." --model-out model.joblib` (`--tune` re-runs the hyperparameter grid search — do this if more job-posting PDFs are added, since the current tuned settings were chosen for a 100-posting/5-role dataset and the optimum can shift). Older `model.joblib` files may lack `svd`/`normalizer` keys — `match.py`'s `score_resume` falls back to raw TF-IDF for those.
- `match.py` — `score_resume(artifacts, resume_text)`: returns each role's `ml_match_pct` (classifier probability, sums to 100% across roles) and `similarity_pct` (cosine similarity to that role's postings in the reduced feature space, independent per role — used as a sanity check against the classifier). Also `score_resume_against_text(artifacts, resume_text, target_text)`: cosine-similarity match % (no classifier involved) between a resume and *arbitrary* text in the same reduced TF-IDF→SVD→normalizer space — used to score a resume against one internship position's own title/requirements/description, text the classifier was never trained on. Returns a single float 0–100, independent of the 5 trained categories.

**Integration in `app.py`**: the model is loaded once at import time (`_resume_model`); if loading fails (missing file/deps) the app still starts, `_resume_model_error` is set, and resume upload just skips scoring with a warning flag — it never crashes the app. `run_resume_match()` wraps `score_resume` and normalizes numpy types (`numpy.str_`/`numpy.float64`) to plain `str`/`float` before they're used as MySQL query params, since some driver versions reject numpy scalars. Resume uploads happen through `candidate_profile()` (PDF only, saved to `static/uploads/resumes/`, filename prefixed `user<id>_`); match results are stored as a JSON blob (`candidate_profiles.resume_match_json`) plus denormalized `resume_best_role`/`resume_best_pct` columns for quick display on the candidate dashboard. `resume_text` (the raw PDF extraction) is cached alongside it so per-position matching doesn't need to re-parse the PDF on every view — it's saved even when the 5-category classifier scoring fails, as long as extraction itself produced usable text.

**Per-position applicant ranking**: `score_against_position(resume_text, position)` (in `app.py`) wraps `score_resume_against_text`, building the target text from `f"{position['title']} {position['requirements']} {position['description']}"`. `/hr/positions/<id>/applicants` (`hr_position_applicants`) computes this for every applicant against that specific position and sorts the list best-match-first (`None` scores — missing resume or unavailable model — sort last). For applicants whose resume was uploaded before this feature existed (no cached `resume_text`), it's extracted from the saved PDF and backfilled into `candidate_profiles.resume_text` on first view of that page, so the re-parse only happens once per candidate.
