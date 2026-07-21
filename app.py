"""
DRDO Internship Portal - Flask Backend
=======================================
Roles: admin | hr | candidate
Run:   python app.py
"""

from flask import (Flask, render_template, request, redirect,
                   url_for, session, flash, g)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import mysql.connector
from functools import wraps
from datetime import datetime
import json
import os
import re
import sys
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get(
    "SECRET_KEY", "dev-secret-change-me")

# ──────────────────────────────────────────────
# RESUME ↔ JOB-ROLE MATCHER
# ──────────────────────────────────────────────
# resume_matcher/ is a plain (non-package) module folder - its own files
# import each other with bare names (e.g. "from pdf_utils import ..."), so
# it's added to sys.path rather than imported as "resume_matcher.match".
RESUME_MATCHER_DIR = os.path.join(os.path.dirname(
    os.path.abspath(__file__)), "resume_matcher")
sys.path.insert(0, RESUME_MATCHER_DIR)

RESUME_UPLOAD_FOLDER = os.path.join(
    app.root_path, "static", "uploads", "resumes")
os.makedirs(RESUME_UPLOAD_FOLDER, exist_ok=True)
ALLOWED_RESUME_EXTENSIONS = {"pdf"}

_resume_model = None
_resume_model_error = None
try:
    import joblib
    from match import score_resume, score_resume_against_text
    from pdf_utils import extract_text_from_pdf

    _model_path = os.path.join(RESUME_MATCHER_DIR, "model.joblib")
    _resume_model = joblib.load(_model_path)
except Exception as exc:  # missing model file, missing deps, etc.
    _resume_model_error = str(exc)
    print(f"[warn] Resume matcher unavailable: {_resume_model_error}")


def allowed_resume_file(filename: str) -> bool:
    """True if filename has an extension in ALLOWED_RESUME_EXTENSIONS (PDF only)."""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_RESUME_EXTENSIONS


def clean_resume_filename(filename: str) -> str:
    """Strip any existing user<id>_ prefix(es) before the caller adds its own,
    so re-uploading a resume that was previously downloaded/renamed with that
    prefix still attached doesn't stack prefixes indefinitely
    (user3_user3_user3_...)."""
    return re.sub(r"^(?:user\d+_)+", "", filename)


def run_resume_match(pdf_path: str):
    """Score a resume PDF against the trained job-role model.

    Returns (results, error, resume_text). results is the same list of
    {role, ml_match_pct, similarity_pct} dicts produced by
    resume_matcher/match.py, sorted best-fit first. resume_text is the
    extracted plain text, returned only when it was usable (so callers can
    cache it for later per-position matching); it's None on any failure.
    """
    if _resume_model is None:
        return None, _resume_model_error or "Resume matcher model is not available.", None

    resume_text = extract_text_from_pdf(pdf_path)
    if len(resume_text.split()) < 5:
        return None, "Could not extract meaningful text from that PDF - is it a scanned image?", None

    try:
        results = score_resume(_resume_model, resume_text)
    except Exception as exc:
        return None, f"Scoring failed: {exc}", None

    # score_resume's roles come from the sklearn classifier's classes_ array
    # (numpy.str_), which some MySQL driver versions choke on when bound as
    # a query parameter - normalize to plain str/float before returning.
    results = [
        {"role": str(r["role"]), "ml_match_pct": float(r["ml_match_pct"]),
         "similarity_pct": float(r["similarity_pct"])}
        for r in results
    ]
    return results, None, resume_text


def score_against_position(resume_text: str, position: dict):
    """Cosine-similarity match % between a candidate's cached resume text and
    one specific internship position's own title/requirements/description.
    Returns None if the model isn't loaded or resume_text is empty.
    """
    if _resume_model is None or not resume_text:
        return None
    target_text = f"{position['title']} {position.get('requirements') or ''} {position.get('description') or ''}"
    try:
        return score_resume_against_text(_resume_model, resume_text, target_text)
    except Exception:
        return None


# ──────────────────────────────────────────────
# DATABASE CONFIG  (edit as needed)
# ──────────────────────────────────────────────
DB_CONFIG = {
    "host":     os.environ.get("DB_HOST", "localhost"),
    "user":     os.environ.get("DB_USER", "root"),
    # Set DB_PASS in your local .env file (see .env.example) — never hardcode it here.
    "password": os.environ.get("DB_PASS", ""),
    "database": os.environ.get("DB_NAME", "drdo_portal"),
    "autocommit": False,
}


def get_db():
    """Return a per-request DB connection."""
    if "db" not in g:
        g.db = mysql.connector.connect(**DB_CONFIG)
    return g.db


@app.teardown_appcontext
def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query(sql, params=(), one=False, commit=False):
    """Helper: execute SQL, return rows or lastrowid."""
    db = get_db()
    cur = db.cursor(dictionary=True)
    cur.execute(sql, params)
    if commit:
        db.commit()
        return cur.lastrowid
    rows = cur.fetchall()
    return rows[0] if (one and rows) else rows


# ──────────────────────────────────────────────
# AUTH DECORATORS
# ──────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if session.get("role") not in roles:
                flash("Access denied.", "danger")
                return redirect(url_for("login"))
            return f(*args, **kwargs)
        return decorated
    return decorator


# ──────────────────────────────────────────────
# PUBLIC ROUTES
# ──────────────────────────────────────────────
@app.route("/")
def index():
    """Landing route: bounce to the caller's role-specific dashboard, or to login."""
    if "user_id" in session:
        return redirect(url_for(f"{session['role']}_dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    """Email/password login; starts a session and redirects to the user's dashboard."""
    if "user_id" in session:
        return redirect(url_for("index"))

    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        user = query("SELECT * FROM users WHERE email=%s AND is_active=1",
                     (email,), one=True)

        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["user_name"] = user["full_name"]
            session["role"] = user["role"]
            flash(f"Welcome, {user['full_name']}!", "success")
            return redirect(url_for("index"))
        flash("Invalid email or password.", "danger")

    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Self-service candidate signup. Always creates a paired candidate_profiles
    row so later profile edits (see candidate_profile()) actually persist."""
    if request.method == "POST":
        full_name = request.form["full_name"].strip()
        email = request.form["email"].strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form["password"]
        confirm = request.form["confirm_password"]

        if password != confirm:
            flash("Passwords do not match.", "danger")
            return render_template("register.html")

        existing = query("SELECT id FROM users WHERE email=%s",
                         (email,), one=True)
        if existing:
            flash("Email already registered.", "danger")
            return render_template("register.html")

        hashed = generate_password_hash(password)
        uid = query(
            "INSERT INTO users (full_name, email, password_hash, role, phone) VALUES (%s,%s,%s,'candidate',%s)",
            (full_name, email, hashed, phone), commit=True
        )
        # create empty profile
        query("INSERT INTO candidate_profiles (user_id) VALUES (%s)",
              (uid,), commit=True)
        flash("Registration successful! Please log in.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/logout")
def logout():
    """Clear the session and return to login."""
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for("login"))


# ──────────────────────────────────────────────
# CANDIDATE ROUTES
# ──────────────────────────────────────────────
@app.route("/candidate/dashboard")
@login_required
@role_required("candidate")
def candidate_dashboard():
    """Candidate home: their applications plus their latest resume↔role match, if any."""
    apps = query("""
        SELECT a.*, ip.title, ip.department, ip.location, ip.stipend
        FROM applications a
        JOIN internship_positions ip ON ip.id = a.position_id
        WHERE a.candidate_id = %s
        ORDER BY a.applied_at DESC
    """, (session["user_id"],))

    profile = query("SELECT * FROM candidate_profiles WHERE user_id=%s",
                    (session["user_id"],), one=True)
    resume_match = None
    if profile and profile.get("resume_match_json"):
        resume_match = {
            "best_role": profile["resume_best_role"],
            "best_pct": profile["resume_best_pct"],
            "breakdown": json.loads(profile["resume_match_json"]),
        }

    return render_template("candidate_dashboard.html", applications=apps, resume_match=resume_match)


@app.route("/candidate/apply", methods=["GET", "POST"])
@login_required
@role_required("candidate")
def candidate_apply():
    """List open positions (GET) or submit an application to one (POST),
    guarding against duplicate applications to the same position."""
    positions = query("""
        SELECT ip.*, u.full_name AS hr_name
        FROM internship_positions ip
        JOIN users u ON u.id = ip.created_by
        WHERE ip.is_active=1 AND (ip.deadline IS NULL OR ip.deadline >= CURDATE())
        ORDER BY ip.created_at DESC
    """)

    if request.method == "POST":
        pos_id = request.form["position_id"]
        cover_letter = request.form.get("cover_letter", "").strip()

        # check duplicate
        dup = query("SELECT id FROM applications WHERE candidate_id=%s AND position_id=%s",
                    (session["user_id"], pos_id), one=True)
        if dup:
            flash("You have already applied for this position.", "warning")
            return redirect(url_for("candidate_dashboard"))

        app_id = query(
            "INSERT INTO applications (candidate_id, position_id, cover_letter) VALUES (%s,%s,%s)",
            (session["user_id"], pos_id, cover_letter), commit=True
        )
        # log history
        query(
            "INSERT INTO application_history (application_id, old_status, new_status, remarks, changed_by) VALUES (%s,%s,%s,%s,%s)",
            (app_id, None, "Submitted",
             "Application submitted by candidate.", session["user_id"]),
            commit=True
        )
        flash("Application submitted successfully!", "success")
        return redirect(url_for("candidate_dashboard"))

    return render_template("candidate_apply.html", positions=positions)


@app.route("/candidate/application/<int:app_id>")
@login_required
@role_required("candidate")
def candidate_application_detail(app_id):
    """Single application view with its full status-change history, scoped to the
    logged-in candidate so one candidate can't view another's application by ID."""
    application = query("""
        SELECT a.*, ip.title, ip.department, ip.location, ip.description,
               ip.stipend, ip.duration
        FROM applications a
        JOIN internship_positions ip ON ip.id = a.position_id
        WHERE a.id=%s AND a.candidate_id=%s
    """, (app_id, session["user_id"]), one=True)

    if not application:
        flash("Application not found.", "danger")
        return redirect(url_for("candidate_dashboard"))

    history = query("""
        SELECT ah.*, u.full_name AS changed_by_name
        FROM application_history ah
        JOIN users u ON u.id = ah.changed_by
        WHERE ah.application_id=%s
        ORDER BY ah.changed_at ASC
    """, (app_id,))

    return render_template("candidate_application_detail.html",
                           application=application, history=history)


# ──────────────────────────────────────────────
# HR ROUTES
# ──────────────────────────────────────────────
@app.route("/hr/dashboard")
@login_required
@role_required("hr")
def hr_dashboard():
    """HR home: portal-wide application counts by status, plus the full application list."""
    stats = {
        "total":      query("SELECT COUNT(*) AS c FROM applications", one=True)["c"],
        "submitted":  query("SELECT COUNT(*) AS c FROM applications WHERE status='Submitted'", one=True)["c"],
        "shortlisted": query("SELECT COUNT(*) AS c FROM applications WHERE status='Shortlisted'", one=True)["c"],
        "selected":   query("SELECT COUNT(*) AS c FROM applications WHERE status='Selected'", one=True)["c"],
    }
    applications = query("""
        SELECT a.*, u.full_name AS candidate_name, u.email AS candidate_email,
               ip.title AS position_title, ip.department
        FROM applications a
        JOIN users u  ON u.id  = a.candidate_id
        JOIN internship_positions ip ON ip.id = a.position_id
        ORDER BY a.applied_at DESC
    """)
    return render_template("hr_dashboard.html", stats=stats, applications=applications)


@app.route("/hr/application/<int:app_id>", methods=["GET", "POST"])
@login_required
@role_required("hr")
def hr_application_detail(app_id):
    """Single application review screen. GET shows candidate/profile/position
    details and history; POST records a status change and appends to the
    application_history audit trail."""
    application = query("""
        SELECT a.*, u.full_name AS candidate_name, u.email AS candidate_email,
               u.phone AS candidate_phone,
               ip.title, ip.department, ip.location, ip.description,
               ip.stipend, ip.duration,
               cp.college, cp.degree, cp.branch, cp.graduation_year,
               cp.cgpa, cp.skills
        FROM applications a
        JOIN users u  ON u.id = a.candidate_id
        LEFT JOIN candidate_profiles cp ON cp.user_id = u.id
        JOIN internship_positions ip ON ip.id = a.position_id
        WHERE a.id=%s
    """, (app_id,), one=True)

    if not application:
        flash("Application not found.", "danger")
        return redirect(url_for("hr_dashboard"))

    if request.method == "POST":
        new_status = request.form["status"]
        remarks = request.form.get("remarks", "").strip()
        old_status = application["status"]

        query("UPDATE applications SET status=%s, hr_remarks=%s WHERE id=%s",
              (new_status, remarks, app_id), commit=True)
        query("""
            INSERT INTO application_history
            (application_id, old_status, new_status, remarks, changed_by)
            VALUES (%s,%s,%s,%s,%s)
        """, (app_id, old_status, new_status, remarks, session["user_id"]), commit=True)

        flash(f"Status updated to '{new_status}'.", "success")
        return redirect(url_for("hr_application_detail", app_id=app_id))

    history = query("""
        SELECT ah.*, u.full_name AS changed_by_name
        FROM application_history ah
        JOIN users u ON u.id = ah.changed_by
        WHERE ah.application_id=%s
        ORDER BY ah.changed_at ASC
    """, (app_id,))

    statuses = ["Submitted", "Under Review", "Shortlisted",
                "Interview Scheduled", "Selected", "Rejected"]
    return render_template("hr_application_detail.html",
                           application=application, history=history,
                           statuses=statuses)


@app.route("/hr/positions", methods=["GET", "POST"])
@login_required
@role_required("hr")
def hr_positions():
    """List positions created by the logged-in HR user (GET) or create a new one (POST)."""
    if request.method == "POST":
        query("""
            INSERT INTO internship_positions
            (title, department, location, description, requirements,
             duration, stipend, total_seats, deadline, created_by)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            request.form["title"],
            request.form["department"],
            request.form.get("location", "DRDO HQ, New Delhi"),
            request.form.get("description", ""),
            request.form.get("requirements", ""),
            request.form.get("duration", ""),
            request.form.get("stipend") or None,
            int(request.form.get("total_seats", 1)),
            request.form.get("deadline") or None,
            session["user_id"]
        ), commit=True)
        flash("Internship position created!", "success")
        return redirect(url_for("hr_positions"))

    positions = query("""
        SELECT ip.*,
               (SELECT COUNT(*) FROM applications a WHERE a.position_id=ip.id) AS applicant_count
        FROM internship_positions ip
        WHERE ip.created_by=%s
        ORDER BY ip.created_at DESC
    """, (session["user_id"],))
    return render_template("hr_positions.html", positions=positions)


@app.route("/hr/positions/<int:pos_id>/toggle")
@login_required
@role_required("hr")
def hr_toggle_position(pos_id):
    """Flip a position between active/closed. Scoped to created_by so HR can only
    toggle their own postings."""
    pos = query("SELECT is_active FROM internship_positions WHERE id=%s AND created_by=%s",
                (pos_id, session["user_id"]), one=True)
    if pos:
        new_val = 0 if pos["is_active"] else 1
        query("UPDATE internship_positions SET is_active=%s WHERE id=%s",
              (new_val, pos_id), commit=True)
        flash("Position updated.", "success")
    return redirect(url_for("hr_positions"))


@app.route("/hr/positions/<int:pos_id>/applicants")
@login_required
@role_required("hr")
def hr_position_applicants(pos_id):
    """Applicants for one position, ranked best-match-first against that position's
    own title/requirements/description text (see score_against_position)."""
    position = query("SELECT * FROM internship_positions WHERE id=%s AND created_by=%s",
                     (pos_id, session["user_id"]), one=True)
    if not position:
        flash("Position not found.", "danger")
        return redirect(url_for("hr_positions"))

    applications = query("""
        SELECT a.*, u.full_name AS candidate_name, u.email AS candidate_email,
               cp.resume_url, cp.resume_text
        FROM applications a
        JOIN users u ON u.id = a.candidate_id
        LEFT JOIN candidate_profiles cp ON cp.user_id = u.id
        WHERE a.position_id=%s
    """, (pos_id,))

    for app_row in applications:
        resume_text = app_row["resume_text"]
        # Pre-existing resumes uploaded before per-position matching was
        # added won't have cached text yet - extract and backfill once.
        if not resume_text and app_row["resume_url"]:
            resume_path = os.path.join(
                app.root_path, "static", app_row["resume_url"])
            try:
                resume_text = extract_text_from_pdf(resume_path)
                if len(resume_text.split()) < 5:
                    resume_text = None
            except Exception:
                resume_text = None
            if resume_text:
                query("UPDATE candidate_profiles SET resume_text=%s WHERE user_id=%s",
                      (resume_text, app_row["candidate_id"]), commit=True)
        app_row["match_pct"] = score_against_position(resume_text, position)

    applications.sort(key=lambda a: (
        a["match_pct"] is None, -(a["match_pct"] or 0)))

    return render_template("hr_position_applicants.html", position=position,
                           applications=applications, model_available=_resume_model is not None)


# ──────────────────────────────────────────────
# ADMIN ROUTES
# ──────────────────────────────────────────────
@app.route("/admin/dashboard")
@login_required
@role_required("admin")
def admin_dashboard():
    """Admin home: portal-wide user/position/application counts and the full user list."""
    stats = {
        "users":        query("SELECT COUNT(*) AS c FROM users", one=True)["c"],
        "hrs":          query("SELECT COUNT(*) AS c FROM users WHERE role='hr'", one=True)["c"],
        "candidates":   query("SELECT COUNT(*) AS c FROM users WHERE role='candidate'", one=True)["c"],
        "positions":    query("SELECT COUNT(*) AS c FROM internship_positions", one=True)["c"],
        "applications": query("SELECT COUNT(*) AS c FROM applications", one=True)["c"],
    }
    users = query(
        "SELECT id, full_name, email, role, phone, is_active, created_at FROM users ORDER BY created_at DESC")
    return render_template("admin_dashboard.html", stats=stats, users=users)


@app.route("/admin/users/<int:uid>/toggle")
@login_required
@role_required("admin")
def admin_toggle_user(uid):
    """Activate/deactivate a user account. Deactivated users can't log in (see login())."""
    user = query("SELECT is_active FROM users WHERE id=%s", (uid,), one=True)
    if user:
        query("UPDATE users SET is_active=%s WHERE id=%s",
              (0 if user["is_active"] else 1, uid), commit=True)
        flash("User status updated.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/add_hr", methods=["POST"])
@login_required
@role_required("admin")
def admin_add_hr():
    """Create a new HR account. HR accounts are admin-provisioned only; there is
    no self-registration path for this role."""
    full_name = request.form["full_name"].strip()
    email = request.form["email"].strip().lower()
    password = request.form["password"]
    phone = request.form.get("phone", "").strip()

    existing = query("SELECT id FROM users WHERE email=%s", (email,), one=True)
    if existing:
        flash("Email already registered.", "danger")
        return redirect(url_for("admin_dashboard"))

    hashed = generate_password_hash(password)
    query("INSERT INTO users (full_name, email, password_hash, role, phone) VALUES (%s,%s,%s,'hr',%s)",
          (full_name, email, hashed, phone), commit=True)
    flash(f"HR account created for {full_name}.", "success")
    return redirect(url_for("admin_dashboard"))


# ──────────────────────────────────────────────
# CANDIDATE PROFILE UPDATE
# ──────────────────────────────────────────────
@app.route("/candidate/profile", methods=["GET", "POST"])
@login_required
@role_required("candidate")
def candidate_profile():
    """View/edit the candidate's profile fields and (optionally) upload a resume PDF,
    which is scored against the 5 trained job-role categories on upload."""
    profile = query("SELECT * FROM candidate_profiles WHERE user_id=%s",
                    (session["user_id"],), one=True)

    if request.method == "POST":
        query("""
            UPDATE candidate_profiles SET
              dob=%s, gender=%s, address=%s, college=%s, degree=%s,
              branch=%s, graduation_year=%s, cgpa=%s, skills=%s
            WHERE user_id=%s
        """, (
            request.form.get("dob") or None,
            request.form.get("gender") or None,
            request.form.get("address", ""),
            request.form.get("college", ""),
            request.form.get("degree", ""),
            request.form.get("branch", ""),
            request.form.get("graduation_year") or None,
            request.form.get("cgpa") or None,
            request.form.get("skills", ""),
            session["user_id"]
        ), commit=True)

        # Optional resume (re)upload, scored against the trained job-role model.
        resume_file = request.files.get("resume")
        if resume_file and resume_file.filename:
            if not allowed_resume_file(resume_file.filename):
                flash("Resume must be a PDF file.", "danger")
                return redirect(url_for("candidate_profile"))

            filename = secure_filename(
                f"user{session['user_id']}_{clean_resume_filename(resume_file.filename)}")
            save_path = os.path.join(RESUME_UPLOAD_FOLDER, filename)
            resume_file.save(save_path)
            resume_url = f"uploads/resumes/{filename}"

            results, error, resume_text = run_resume_match(save_path)
            if error:
                # Still keep the uploaded file/URL even if scoring failed,
                # just skip the match columns. resume_text is cached too when
                # extraction produced usable text, so per-position matching
                # (HR side) still works even if the 5-category scoring failed.
                query("UPDATE candidate_profiles SET resume_url=%s, resume_text=%s WHERE user_id=%s",
                      (resume_url, resume_text, session["user_id"]), commit=True)
                flash(
                    f"Resume uploaded, but could not be auto-scored: {error}", "warning")
            else:
                best = results[0]
                query("""
                    UPDATE candidate_profiles SET
                      resume_url=%s, resume_best_role=%s, resume_best_pct=%s,
                      resume_match_json=%s, resume_matched_at=%s, resume_text=%s
                    WHERE user_id=%s
                """, (
                    resume_url, best["role"], best["ml_match_pct"],
                    json.dumps(results), datetime.now(
                    ), resume_text, session["user_id"]
                ), commit=True)
                flash(f"Resume uploaded! Best-fit role: {best['role']} "
                      f"({best['ml_match_pct']:.1f}% match).", "success")

        else:
            flash("Profile updated!", "success")

        return redirect(url_for("candidate_profile"))

    resume_match = None
    if profile and profile.get("resume_match_json"):
        resume_match = {
            "best_role": profile["resume_best_role"],
            "best_pct": profile["resume_best_pct"],
            "breakdown": json.loads(profile["resume_match_json"]),
        }

    return render_template("candidate_profile.html", profile=profile, resume_match=resume_match)


# ──────────────────────────────────────────────
# JINJA HELPERS
# ──────────────────────────────────────────────
@app.template_filter("status_color")
def status_color(status):
    """Map an application status to a Bootstrap contextual color class."""
    colors = {
        "Submitted":           "secondary",
        "Under Review":        "info",
        "Shortlisted":         "primary",
        "Interview Scheduled": "warning",
        "Selected":            "success",
        "Rejected":            "danger",
    }
    return colors.get(status, "secondary")


@app.template_filter("datefmt")
def datefmt(value, fmt="%d %b %Y"):
    """Format a date/datetime (or a 'YYYY-MM-DD' string) for display; '—' if empty."""
    if value is None:
        return "—"
    if isinstance(value, str):
        try:
            value = datetime.strptime(value, "%Y-%m-%d")
        except ValueError:
            return value
    return value.strftime(fmt)


if __name__ == "__main__":
    app.run(debug=True, port=5050)
