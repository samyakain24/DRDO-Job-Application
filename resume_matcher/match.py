"""
match.py
--------
Given a trained model and a resume PDF, scores how well the resume matches
each of the 5 job roles.

Two complementary scores are reported for each role:

  * ML Match %  - the trained classifier's predicted probability that this
                  resume belongs to that role (these 5 numbers sum to 100%,
                  since the classifier is choosing the single best-fit role).

  * Similarity %- average cosine similarity (in the model's reduced LSA
                  feature space) between the resume and that role's
                  individual job postings, scaled to 0-100%. Unlike the
                  classifier output, these are independent of each other, so
                  a resume can score high on more than one role. This is
                  useful for interpretability and to sanity-check the
                  classifier's verdict.

Usage:
    python match.py --model model.joblib --resume "../../Sample_AI_ML_Resume_Fictional.pdf"
"""

import argparse
import sys

import joblib
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from pdf_utils import extract_text_from_pdf


def score_resume(artifacts: dict, resume_text: str) -> list:
    vectorizer = artifacts["vectorizer"]
    clf = artifacts["classifier"]
    roles = list(clf.classes_)

    resume_vec = vectorizer.transform([resume_text])

    # Newer models reduce the sparse TF-IDF space with SVD (LSA) before
    # classifying, for better generalization on this small dataset. Older
    # model.joblib files saved before that change won't have these keys, so
    # fall back to raw TF-IDF for backwards compatibility.
    svd = artifacts.get("svd")
    normalizer = artifacts.get("normalizer")
    if svd is not None:
        resume_vec = svd.transform(resume_vec)
        if normalizer is not None:
            resume_vec = normalizer.transform(resume_vec)

    # 1. Classifier-based match %
    proba = clf.predict_proba(resume_vec)[0]
    ml_match = dict(zip(roles, proba * 100))

    # 2. Cosine-similarity-based match % (independent per role)
    posting_vectors = artifacts["posting_vectors"]
    posting_labels = artifacts["posting_labels"]
    sims = cosine_similarity(resume_vec, posting_vectors)[0]

    sim_match = {}
    for role in roles:
        role_sims = sims[posting_labels == role]
        sim_match[role] = float(role_sims.mean() * 100) if len(role_sims) else 0.0

    results = []
    for role in roles:
        results.append({
            "role": role,
            "ml_match_pct": round(float(ml_match[role]), 1),
            "similarity_pct": round(sim_match[role], 1),
        })

    results.sort(key=lambda r: r["ml_match_pct"], reverse=True)
    return results


def score_resume_against_text(artifacts: dict, resume_text: str, target_text: str) -> float:
    """Cosine-similarity match % between a resume and arbitrary target text
    (e.g. one internship position's own title/description/requirements),
    in the same reduced feature space used for the 5-category classifier.
    Unlike score_resume(), this doesn't touch the classifier at all, so it
    works against text the model was never trained on.
    """
    vectorizer = artifacts["vectorizer"]
    svd = artifacts.get("svd")
    normalizer = artifacts.get("normalizer")

    vecs = vectorizer.transform([resume_text, target_text])
    if svd is not None:
        vecs = svd.transform(vecs)
        if normalizer is not None:
            vecs = normalizer.transform(vecs)

    sim = cosine_similarity(vecs[0:1], vecs[1:2])[0][0]
    return round(float(sim) * 100, 1)


def print_results(results: list, resume_path: str):
    print(f"\nMatch results for resume: {resume_path}\n")
    header = f"{'Job Role':<25s} {'ML Match %':>12s} {'Similarity %':>14s}"
    print(header)
    print("-" * len(header))
    for r in results:
        print(f"{r['role']:<25s} {r['ml_match_pct']:>11.1f}% {r['similarity_pct']:>13.1f}%")
    best = results[0]
    print(f"\nBest-fit role: {best['role']} ({best['ml_match_pct']:.1f}% ML match)")


def main():
    parser = argparse.ArgumentParser(description="Score a resume against the 5 trained job roles.")
    parser.add_argument("--model", default="model.joblib", help="Path to trained model .joblib file")
    parser.add_argument("--resume", required=True, help="Path to the resume PDF to score")
    args = parser.parse_args()

    artifacts = joblib.load(args.model)
    resume_text = extract_text_from_pdf(args.resume)

    if len(resume_text.split()) < 5:
        print("[error] Could not extract meaningful text from the resume PDF.", file=sys.stderr)
        return 1

    results = score_resume(artifacts, resume_text)
    print_results(results, args.resume)
    return 0


if __name__ == "__main__":
    sys.exit(main())
