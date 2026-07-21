"""
DRDO Portal - Resume Match & Applicant Ranking (Terminal Demo)
================================================================
Runs the SAME resume-matching / per-position ranking pipeline the front end
uses, entirely from the terminal - no browser required. This does not
reimplement the logic separately; it imports app.py and calls its actual
functions (run_resume_match, score_against_position, query, ...), so the
result is guaranteed to match what a candidate/HR user sees in the browser.

What it does, in order:
  1. Looks up the candidate by email (must already exist - see setup_demo.py).
  2. "Uploads" the given resume PDF exactly like POST /candidate/profile does:
     saves it into static/uploads/resumes/, scores it against the 5 trained
     job-role categories, and writes the match columns back to
     candidate_profiles - same as the candidate profile page.
  3. If --position-id is given, ranks every applicant of that position against
     its own title/requirements/description text - same as the HR
     "ranked applicants" page (/hr/positions/<id>/applicants), including the
     resume_text backfill for pre-existing resumes.

Usage:
    python resume_match_demo.py --email alice@example.com --resume path/to/resume.pdf
    python resume_match_demo.py --email alice@example.com --resume path/to/resume.pdf --position-id 3

Requires the candidate to already exist (run setup_demo.py first) and, for
--position-id, the candidate to have an application on that position.
"""

import argparse
import json
import os
import shutil
import sys
from datetime import datetime

from werkzeug.utils import secure_filename

import app as portal  # reuses DB_CONFIG, query(), run_resume_match(), score_against_position()


def get_candidate(email):
    return portal.query(
        "SELECT * FROM users WHERE email=%s AND role='candidate'", (email,), one=True)


def upload_and_score(user, resume_path):
    """Mirrors the resume-upload branch of candidate_profile() in app.py."""
    if not os.path.isfile(resume_path):
        print(f"ERROR: resume file not found: {resume_path}")
        return None

    filename_only = os.path.basename(resume_path)
    if not portal.allowed_resume_file(filename_only):
        print("ERROR: resume must be a PDF file.")
        return None

    profile = portal.query(
        "SELECT * FROM candidate_profiles WHERE user_id=%s", (user["id"],), one=True)
    if not profile:
        print(f"ERROR: no candidate_profiles row for user_id={user['id']} - "
              "only /register and setup_demo.py create this automatically (see Edits.md).")
        return None

    filename = secure_filename(
        f"user{user['id']}_{portal.clean_resume_filename(filename_only)}")
    save_path = os.path.join(portal.RESUME_UPLOAD_FOLDER, filename)
    shutil.copyfile(resume_path, save_path)
    resume_url = f"uploads/resumes/{filename}"
    print(f"Saved resume -> static/{resume_url}")

    results, error, resume_text = portal.run_resume_match(save_path)

    if error:
        portal.query(
            "UPDATE candidate_profiles SET resume_url=%s, resume_text=%s WHERE user_id=%s",
            (resume_url, resume_text, user["id"]), commit=True)
        print(f"\n[warning] Resume uploaded, but could not be auto-scored: {error}")
        return resume_text

    best = results[0]
    portal.query("""
        UPDATE candidate_profiles SET
          resume_url=%s, resume_best_role=%s, resume_best_pct=%s,
          resume_match_json=%s, resume_matched_at=%s, resume_text=%s
        WHERE user_id=%s
    """, (
        resume_url, best["role"], best["ml_match_pct"],
        json.dumps(results), datetime.now(), resume_text, user["id"]
    ), commit=True)

    print(f"\nMatch results for {user['email']}  "
          "(same numbers the candidate dashboard/profile page shows)\n")
    header = f"{'Job Role':<25s} {'ML Match %':>12s} {'Similarity %':>14s}"
    print(header)
    print("-" * len(header))
    for r in results:
        print(f"{r['role']:<25s} {r['ml_match_pct']:>11.1f}% {r['similarity_pct']:>13.1f}%")
    print(f"\nBest-fit role: {best['role']}  ({best['ml_match_pct']:.1f}% ML match)")
    return resume_text


def rank_applicants(position_id):
    """Mirrors hr_position_applicants() in app.py."""
    position = portal.query(
        "SELECT * FROM internship_positions WHERE id=%s", (position_id,), one=True)
    if not position:
        print(f"ERROR: no internship_positions row with id={position_id}")
        return

    applications = portal.query("""
        SELECT a.*, u.full_name AS candidate_name, u.email AS candidate_email,
               cp.resume_url, cp.resume_text
        FROM applications a
        JOIN users u ON u.id = a.candidate_id
        LEFT JOIN candidate_profiles cp ON cp.user_id = u.id
        WHERE a.position_id=%s
    """, (position_id,))

    if not applications:
        print(f"\nNo applicants yet for position #{position_id} ({position['title']}).")
        return

    for a in applications:
        resume_text = a["resume_text"]
        if not resume_text and a["resume_url"]:
            resume_path = os.path.join(portal.app.root_path, "static", a["resume_url"])
            try:
                resume_text = portal.extract_text_from_pdf(resume_path)
                if len(resume_text.split()) < 5:
                    resume_text = None
            except Exception:
                resume_text = None
            if resume_text:
                portal.query(
                    "UPDATE candidate_profiles SET resume_text=%s WHERE user_id=%s",
                    (resume_text, a["candidate_id"]), commit=True)
        a["match_pct"] = portal.score_against_position(resume_text, position)

    applications.sort(key=lambda a: (a["match_pct"] is None, -(a["match_pct"] or 0)))

    print(f"\nRanked applicants for position #{position_id}: {position['title']}  "
          "(same order the HR 'ranked applicants' page shows)\n")
    header = f"{'Candidate':<25s} {'Email':<28s} {'Match %':>10s}"
    print(header)
    print("-" * len(header))
    for a in applications:
        pct = f"{a['match_pct']:.1f}%" if a["match_pct"] is not None else "n/a"
        print(f"{a['candidate_name']:<25s} {a['candidate_email']:<28s} {pct:>10s}")


def main():
    parser = argparse.ArgumentParser(
        description="Run the resume-matching / applicant-ranking pipeline from the terminal, "
                    "using the exact same functions app.py uses for the front end.")
    parser.add_argument("--email", required=True,
                         help="Candidate's login email (must already exist)")
    parser.add_argument("--resume", required=True,
                         help="Path to a resume PDF to upload+score for that candidate")
    parser.add_argument("--position-id", type=int, default=None,
                         help="Also print ranked applicants for this internship position id")
    args = parser.parse_args()

    with portal.app.app_context():
        try:
            portal.get_db()
            print("Connected to MySQL.\n")
        except Exception as e:
            print(f"ERROR: Could not connect to MySQL.\n{e}")
            return 1

        if portal._resume_model is None:
            print(f"[warning] Resume matcher model unavailable: {portal._resume_model_error}")

        user = get_candidate(args.email)
        if not user:
            print(f"ERROR: no candidate account found for {args.email}. "
                  "Run setup_demo.py or register first.")
            return 1

        upload_and_score(user, args.resume)

        if args.position_id is not None:
            rank_applicants(args.position_id)

    return 0


if __name__ == "__main__":
    sys.exit(main())
