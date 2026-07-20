# DRDO Internship Portal — Feature Development Report

**Scope:** How the portal evolved from a plain application-tracking system into one with an
AI-powered resume↔job-role matcher and per-position applicant ranking.

---

## 1. Starting point — the original portal (built 22 Jun 2026)

Before any AI matching existed, this was a plain **Flask + MySQL** internship application
tracker with three roles: `admin`, `hr`, `candidate`. The original baseline covered account
registration/login, position browsing and applications, the HR review pipeline, and admin user
management — implemented across `app.py` and the core templates (`base.html`, `login.html`,
`register.html`, `admin_dashboard.html`, `hr_dashboard.html`, `hr_application_detail.html`,
`candidate_apply.html`, `candidate_application_detail.html`), with `first_setup.py` and
`setup_demo.py` handling environment bootstrap.

**What it did:**
- Candidates register, browse open internship positions, and apply with a cover letter.
- HR creates/closes positions and moves applications through a status pipeline
  (`Submitted → Under Review → Shortlisted → Interview Scheduled → Selected/Rejected`), with
  every transition logged to an `application_history` audit table.
- Admin manages user accounts (activate/deactivate, create HR accounts) and sees portal-wide
  stats.

**Architecture (unchanged since then):** a single `app.py` file holds every route, using one
`query(sql, params, one=False, commit=False)` helper for all raw parameterized SQL (no ORM),
session-based auth via two decorators (`@login_required`, `@role_required(...)`), and Jinja2
templates named `<role>_<page>.html`.

**Data model at this stage:** `users` → `candidate_profiles` (1:1) / `internship_positions`
(created by HR) → `applications` (candidate × position) → `application_history`.
`candidate_profiles` held only personal/academic fields (`dob`, `college`, `degree`, `cgpa`,
`skills`, etc.) plus a bare `resume_url` — resumes could be uploaded but nothing read or scored
them.

**The gap:** HR had no way to gauge fit beyond reading a cover letter and profile fields by eye,
and candidates got no feedback on which roles suited their resume.

---

## 2. Feature 1 — Resume ↔ job-role matcher (7 Jul 2026)

**Requirement:** score an uploaded resume PDF against a fixed set of 5 trained job-role
categories, so candidates see a best-fit role and HR gets a data point beyond the raw resume.

### 2.1 New module: `resume_matcher/`
Added as a **plain module folder, not a Python package** — its files import each other with
bare names (`from pdf_utils import extract_text_from_pdf`) rather than dotted imports, so
`app.py` inserts `resume_matcher/` onto `sys.path` at startup instead of importing it as
`resume_matcher.match`.

| File | Purpose |
|---|---|
| `pdf_utils.py` | `extract_text_from_pdf()` — pulls text per-page via `pypdf`, strips lone bullet-character lines, collapses whitespace. |
| `dataset.py` | Walks `<role> jobs/*.pdf` folders (one folder per job-role category, one PDF per sample posting) to build labeled training examples — folder name is the label. |
| `train_model.py` | Full training pipeline (see §2.2). |
| `match.py` | `score_resume(artifacts, resume_text)` — runtime scoring against the 5 trained roles. |
| `model.joblib` | The trained, serialized model artifact (~575 KB). |

### 2.2 The ML pipeline
`train_model.py` grid-searched several options against repeated Stratified K-Fold CV on a
100-posting/5-role dataset before landing on:

**TF-IDF → TruncatedSVD(60 components, LSA) → Normalizer → LogisticRegression**
(`class_weight="balanced"`, `C=1.0`)

Why SVD: with only 100 short, jargon-heavy training postings, raw TF-IDF has far more
dimensions than examples and overfits; reducing to 60 dense LSA components generalizes better.
Accuracy progression found during tuning: raw TF-IDF+LogReg ≈ 64%, tuned TF-IDF (no SVD) ≈
65–66%, tuned TF-IDF+SVD(60)+LogReg ≈ 67% and more stable across CV seeds — the version that
shipped. LinearSVC, RBF-SVC, Naive Bayes, char n-grams, χ² feature selection, and
voting/stacking ensembles were all tried and didn't beat it.

Each resume gets two complementary numbers per role, computed by `score_resume()`:
- **ML Match %** — the classifier's `predict_proba`, five numbers summing to 100% (it's picking
  one best-fit role).
- **Similarity %** — cosine similarity to that role's own training postings in the reduced LSA
  space, independent per role, used as a sanity check against the classifier's verdict.

### 2.3 Schema change
`migrate_resume_match.sql` (written for databases created before this feature) adds four
columns to `candidate_profiles`:
```sql
resume_best_role  VARCHAR(100)
resume_best_pct   DECIMAL(5,2)
resume_match_json TEXT
resume_matched_at DATETIME
```

### 2.4 Integration into `app.py`
- The model loads **once at import time** into `_resume_model`. If loading fails (missing file
  or missing deps), the app still starts — `_resume_model_error` is set and resume upload just
  skips scoring with a warning flag, rather than crashing the whole portal.
- `run_resume_match(pdf_path)` wraps `score_resume`, extracts text, rejects unusably short
  extractions (<5 words — likely a scanned/image-only PDF), and **normalizes numpy scalar types
  to plain Python `str`/`float`** before they're used as MySQL query parameters, since some
  `mysql-connector` versions reject `numpy.str_`/`numpy.float64` bound params directly.
- Upload path lives in `candidate_profile()` (`POST /candidate/profile`): PDF-only validation,
  saved to `static/uploads/resumes/` with filename prefixed `user<id>_`, then scored. Results
  are stored as a JSON blob (`resume_match_json`) plus denormalized `resume_best_role` /
  `resume_best_pct` for fast dashboard display.
- `candidate_dashboard()` and `candidate_profile()` both read `resume_match_json` back out and
  reshape it into `{best_role, best_pct, breakdown}` for the templates.

### 2.5 Templates touched
`candidate_profile.html` (resume upload form + match breakdown display) and
`candidate_dashboard.html` (best-fit role summary card) were updated to surface the new data.

---

## 3. Feature 2 — Per-position applicant ranking (12 Jul 2026)

**Requirement:** the 5-category classifier is useful for self-discovery, but it can't tell HR
how well a candidate fits *one specific open position* — that position's actual title/
requirements/description text was never part of the classifier's training set. HR needed
applicants for a given posting ranked by fit to that posting.

### 3.1 New scoring function: `score_resume_against_text()`
Added to `resume_matcher/match.py`. Unlike `score_resume()`, it never touches the classifier —
it embeds the resume and an arbitrary piece of target text (a position's own copy) into the same
TF-IDF → SVD → Normalizer space and returns their cosine similarity as a single 0–100 float,
independent of the 5 trained categories.

### 3.2 Schema change
`migrate_position_match.sql` adds one column:
```sql
candidate_profiles.resume_text TEXT
```
This caches the raw plain-text PDF extraction (not the match results — the text itself), so
scoring against an arbitrary position doesn't require re-parsing the resume PDF on every page
view.

### 3.3 Integration into `app.py`
- `score_against_position(resume_text, position)`: builds target text as
  `f"{title} {requirements} {description}"` and calls `score_resume_against_text`. Returns
  `None` if the model isn't loaded or there's no resume text, so callers can distinguish "no
  score available" from "0% match."
- New route `GET /hr/positions/<id>/applicants` (`hr_position_applicants`): loads every
  applicant for that position, scores each against it, and sorts best-match-first — with `None`
  scores (no resume, or model unavailable) sorted last rather than crashing the sort.
- **Backfill for pre-existing resumes:** applicants who uploaded a resume *before* this feature
  shipped have no cached `resume_text`. On first view of the applicants page, their PDF is
  re-extracted from the saved file and the result is written back to
  `candidate_profiles.resume_text`, so the re-parse cost is paid once per candidate, not once
  per page view.
- `candidate_profile()`'s upload path was extended to also populate `resume_text` on every
  upload going forward — including when the 5-category scoring itself fails but text extraction
  succeeded, so per-position matching keeps working independently of classifier success.

### 3.4 Templates
- **New:** `hr_position_applicants.html` — ranked applicant table with a color-coded match badge
  (green ≥50%, amber ≥25%, gray below/no resume) and a warning banner if the model failed to
  load.
- **Updated:** `hr_positions.html` — each position card's applicant count now links through to
  the new ranked-applicants page.

---

## 4. Hardening & consolidation (14 Jul 2026)

The final pass — reflected in the current `app.py`, `schema.sql`, and the newly written
`Edits.md` — folded both migrations into a single canonical `schema.sql` (so a fresh install
gets `resume_best_role`, `resume_best_pct`, `resume_match_json`, `resume_matched_at`, and
`resume_text` from one `CREATE TABLE`, with the two migration scripts kept around only for
upgrading pre-existing databases) and tightened a few correctness details that a first pass
tends to miss:

- **Silent-failure guard, documented in `Edits.md`:** `schema.sql`'s seed data explicitly pairs
  every seeded candidate with an `INSERT INTO candidate_profiles (user_id)` row, because
  `candidate_profile()`'s `UPDATE ... WHERE user_id=%s` affects 0 rows (looks like success,
  saves nothing) if that row is missing. Only `/register` and `setup_demo.py` create it
  automatically — a documented trap for anyone inserting candidates by hand.
- **numpy → MySQL param coercion** in `run_resume_match` (see §2.4) — a concrete driver
  incompatibility that would otherwise surface as an opaque `mysql.connector` error on save.
- **Graceful degradation everywhere the model touches user-facing flow:** missing model file →
  app still boots; short/unparseable PDF → clear flash message instead of a 500; failed
  classifier scoring → resume and `resume_text` are still saved, only the match badge is
  skipped.
- **`requirements.txt`** extended beyond the original Flask/MySQL/Werkzeug trio with
  `scikit-learn`, `pypdf`, `joblib`, `numpy` for the matcher.

---

## 5. Files changed, end to end

| File | Status | Change |
|---|---|---|
| `resume_matcher/pdf_utils.py` | new | PDF text extraction |
| `resume_matcher/dataset.py` | new | Training-data loader |
| `resume_matcher/train_model.py` | new | Training pipeline (TF-IDF→SVD→LogReg) |
| `resume_matcher/match.py` | new, then extended | `score_resume` (Jul 7), `score_resume_against_text` added (Jul 12) |
| `resume_matcher/model.joblib` | new | Trained model artifact |
| `migrate_resume_match.sql` | new | Adds 4 match columns (Jul 7) |
| `migrate_position_match.sql` | new | Adds `resume_text` column (Jul 12) |
| `schema.sql` | modified | Consolidated final schema incl. all 5 new columns + seed-data profile pairing fix |
| `app.py` | modified | Model bootstrap, `run_resume_match`, `score_against_position`, upload handling in `candidate_profile()`, new `hr_position_applicants` route, dashboard breakdown wiring |
| `requirements.txt` | modified | Added `scikit-learn`, `pypdf`, `joblib`, `numpy` |
| `templates/candidate_profile.html` | modified | Resume upload + match breakdown UI |
| `templates/candidate_dashboard.html` | modified | Best-fit role summary card |
| `templates/hr_positions.html` | modified | Applicant count links to ranked-applicants page |
| `templates/hr_position_applicants.html` | new | Ranked applicant table with match badges |
| `Edits.md` | new | Architecture/onboarding notes for future contributors |

---

## 6. Data model, before → after

```
BEFORE                              AFTER
users                               users
  └─ candidate_profiles               └─ candidate_profiles
       (personal/academic fields           (... same fields ...)
        + resume_url only)                 + resume_url
                                            + resume_best_role      ← Feature 1
internship_positions                       + resume_best_pct       ← Feature 1
  └─ applications                          + resume_match_json     ← Feature 1
       └─ application_history              + resume_matched_at     ← Feature 1
                                            + resume_text           ← Feature 2

                                     internship_positions            (unchanged)
                                       └─ applications                (unchanged)
                                            └─ application_history    (unchanged)
```

## 7. Current known limitations (for future work)

- The 5-category classifier's cross-validated accuracy is ~67% (±8%) on a 100-posting dataset —
  usable as a signal, not a hard filter. `train_model.py --tune` should be re-run whenever more
  job-posting PDFs are added, since the tuned hyperparameters were chosen for this dataset size
  and the optimum can shift.
- Scanned/image-only resume PDFs produce no extractable text and are rejected at upload with a
  flash message rather than silently scoring as 0%.
- There is still no automated test suite or linter configured in the repo (per `Edits.md`) —
  both features were verified manually against the demo accounts.
