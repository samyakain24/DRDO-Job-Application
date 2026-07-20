"""
train_model.py
---------------
Trains the job-role matching model.

Pipeline:
  1. Load every job posting PDF for each of the 5 role folders as a labeled
     training example (text = requirements, label = role name).
  2. Fit a TF-IDF vectorizer over all job postings.
  3. Reduce the sparse TF-IDF space with truncated SVD (LSA) down to a
     small number of dense components, L2-normalized. With only 100
     training postings (20/role) and short, jargon-heavy text, the raw
     TF-IDF space has far more dimensions than examples, which invites
     overfitting; SVD compresses to the directions that actually separate
     the roles and generalizes better.
  4. Train a Logistic Regression classifier on the reduced features to
     predict role. This is the model that will later score a resume's
     match % against each role.
  5. Report cross-validated accuracy (repeated Stratified K-Fold, which is
     far less noisy than a single 5-fold split on a 100-row dataset) so you
     know how well the model actually separates the 5 roles.
  6. Save the vectorizer, SVD, normalizer, classifier, and per-posting
     vectors (used later for a cosine-similarity sanity-check score) to a
     single .joblib file.

The settings below were chosen by grid-searching TF-IDF ngram range,
min_df/max_df, SVD component count, and classifier regularization against
repeated 5-fold cross-validation (20-30 repeats) on this dataset (100
postings across 5 roles):
  - raw TF-IDF + LogReg defaults:               ~64% (+/- 8%)
  - tuned TF-IDF + LogReg, no SVD (old default): ~65-66% (+/- 8%)
  - tuned TF-IDF + SVD(60) + LogReg (current):   ~67% (+/- 8%), consistent
    across repeated-CV runs with different random seeds.
Other approaches tried and rejected because they didn't beat this: LinearSVC,
SVC(rbf), Naive Bayes, char n-grams, chi2 feature selection, and
voting/stacking ensembles of the above. Pass --tune to re-run a param search
yourself (useful if you add more job postings later, since the optimum can
shift, and it likely will improve further with more data - 20 postings/role
is a small sample for this many roles).

Usage:
    python train_model.py --data-dir "../.." --model-out model.joblib
    python train_model.py --data-dir "../.." --model-out model.joblib --tune
"""

import argparse
import sys

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import RepeatedStratifiedKFold, cross_val_score, GridSearchCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import TruncatedSVD
from sklearn.preprocessing import Normalizer
from sklearn.pipeline import Pipeline

from dataset import load_job_role_dataset, dataset_summary

# Tuned via repeated-CV grid search (see --tune). Re-run with --tune whenever
# the training data changes meaningfully (more postings, new roles, etc.).
TUNED_VECTORIZER_PARAMS = dict(
    lowercase=True,
    stop_words="english",
    ngram_range=(1, 2),
    min_df=2,
    max_df=0.75,
    sublinear_tf=True,
)
TUNED_SVD_PARAMS = dict(
    n_components=60,
    random_state=42,
)
TUNED_CLASSIFIER_PARAMS = dict(
    max_iter=3000,
    class_weight="balanced",
    C=1.0,
)


def build_vectorizer() -> TfidfVectorizer:
    return TfidfVectorizer(**TUNED_VECTORIZER_PARAMS)


def build_svd() -> TruncatedSVD:
    return TruncatedSVD(**TUNED_SVD_PARAMS)


def build_normalizer() -> Normalizer:
    return Normalizer(copy=False)


def build_classifier() -> LogisticRegression:
    return LogisticRegression(**TUNED_CLASSIFIER_PARAMS)


def build_pipeline(vectorizer_params=None, svd_params=None, classifier_params=None) -> Pipeline:
    """The full tfidf -> SVD -> normalize -> classifier pipeline, as one object.

    Building it as a single sklearn Pipeline (rather than fitting each stage
    by hand) means cross_val_score refits the vectorizer AND the SVD inside
    every fold, so no information about held-out postings leaks into
    training - that's what makes the reported CV accuracy trustworthy.
    """
    return Pipeline([
        ("tfidf", TfidfVectorizer(**(vectorizer_params or TUNED_VECTORIZER_PARAMS))),
        ("svd", TruncatedSVD(**(svd_params or TUNED_SVD_PARAMS))),
        ("norm", Normalizer(copy=False)),
        ("clf", LogisticRegression(**(classifier_params or TUNED_CLASSIFIER_PARAMS))),
    ])


def tune_hyperparameters(texts, labels, cv) -> dict:
    """Grid-search TF-IDF + SVD + LogisticRegression hyperparameters.

    Returns the best-found vectorizer/svd/classifier kwargs. Only worth
    re-running when the training data has changed (more/fewer postings,
    new roles) since the optimum is specific to this corpus.
    """
    print("\nTuning hyperparameters via grid search (this can take a minute)...")
    pipe = Pipeline([
        ("tfidf", TfidfVectorizer(lowercase=True, stop_words="english", sublinear_tf=True)),
        ("svd", TruncatedSVD(random_state=42)),
        ("norm", Normalizer(copy=False)),
        ("clf", LogisticRegression(max_iter=3000, class_weight="balanced")),
    ])

    param_grid = {
        "tfidf__ngram_range": [(1, 1), (1, 2), (1, 3)],
        "tfidf__min_df": [1, 2, 3],
        "tfidf__max_df": [0.7, 0.75, 0.8, 0.85, 0.9, 1.0],
        "svd__n_components": [40, 50, 60, 70, 90, 100],
        "clf__C": [0.25, 0.5, 1.0, 2.0, 4.0],
    }
    # NOTE: the vectorizer and SVD are both refit inside every fold here (via
    # the Pipeline), so no statistics from held-out postings leak into
    # training. This is the same evaluation protocol used to pick TUNED_*
    # above.
    gs = GridSearchCV(pipe, param_grid, cv=cv, n_jobs=-1)
    gs.fit(texts, labels)

    print(f"Best CV accuracy found: {gs.best_score_:.1%}")
    print(f"Best params: {gs.best_params_}")

    vec_params = dict(TUNED_VECTORIZER_PARAMS)
    vec_params["ngram_range"] = gs.best_params_["tfidf__ngram_range"]
    vec_params["min_df"] = gs.best_params_["tfidf__min_df"]
    vec_params["max_df"] = gs.best_params_["tfidf__max_df"]
    svd_params = dict(TUNED_SVD_PARAMS)
    svd_params["n_components"] = gs.best_params_["svd__n_components"]
    clf_params = dict(TUNED_CLASSIFIER_PARAMS)
    clf_params["C"] = gs.best_params_["clf__C"]
    return {"vectorizer_params": vec_params, "svd_params": svd_params, "classifier_params": clf_params}


def train(data_dir: str, model_out: str, tune: bool = False) -> dict:
    print(f"Loading job postings from: {data_dir}")
    examples = load_job_role_dataset(data_dir)
    print(f"Loaded {len(examples)} job postings across roles:")
    print(dataset_summary(examples))

    texts = [ex.text for ex in examples]
    labels = [ex.label for ex in examples]

    n_splits = min(5, min_class_count(labels))
    # Repeated K-fold gives a much more stable accuracy estimate than a
    # single split when there are only ~20 examples per class - a single
    # 5-fold split can swing several points depending on which postings
    # land in which fold.
    cv = RepeatedStratifiedKFold(n_splits=n_splits, n_repeats=20, random_state=42) if n_splits >= 2 else None

    vectorizer_params = dict(TUNED_VECTORIZER_PARAMS)
    svd_params = dict(TUNED_SVD_PARAMS)
    classifier_params = dict(TUNED_CLASSIFIER_PARAMS)

    if tune and cv is not None:
        best = tune_hyperparameters(texts, labels, cv)
        vectorizer_params = best["vectorizer_params"]
        svd_params = best["svd_params"]
        classifier_params = best["classifier_params"]

    # Cross-validate to estimate how well the model generalizes, given the
    # small-per-class sample size typical of a handful of job postings.
    # Crucially, the vectorizer and SVD are both refit inside each fold (via
    # Pipeline) so test-fold vocabulary/idf/components never leak into
    # training - this matches the protocol used to pick the tuned
    # hyperparameters above.
    if cv is not None:
        eval_pipe = build_pipeline(vectorizer_params, svd_params, classifier_params)
        scores = cross_val_score(eval_pipe, texts, labels, cv=cv, n_jobs=-1)
        print(f"\n{n_splits}-fold cross-validated accuracy ({cv.get_n_splits(texts, labels)} folds total, "
              f"repeated for stability): {scores.mean():.1%} (+/- {scores.std():.1%})")
    else:
        print("\n[warn] Not enough examples per class to cross-validate.")

    # Fit the final model on everything we have.
    vectorizer = TfidfVectorizer(**vectorizer_params)
    X_tfidf = vectorizer.fit_transform(texts)
    svd = TruncatedSVD(**svd_params)
    X_svd = svd.fit_transform(X_tfidf)
    normalizer = Normalizer(copy=False)
    X = normalizer.fit_transform(X_svd)
    clf = LogisticRegression(**classifier_params)
    clf.fit(X, labels)

    artifacts = {
        "vectorizer": vectorizer,
        "svd": svd,
        "normalizer": normalizer,
        "classifier": clf,
        "roles": sorted(set(labels)),
        "posting_vectors": X,
        "posting_labels": np.array(labels),
        "posting_texts": texts,
    }
    joblib.dump(artifacts, model_out)
    print(f"\nSaved trained model to: {model_out}")
    return artifacts


def min_class_count(labels) -> int:
    counts = {}
    for lbl in labels:
        counts[lbl] = counts.get(lbl, 0) + 1
    return min(counts.values()) if counts else 0


def main():
    parser = argparse.ArgumentParser(description="Train the job-role resume matcher model.")
    parser.add_argument("--data-dir", default=".", help="Folder containing the '<role> jobs' sub-folders")
    parser.add_argument("--model-out", default="model.joblib", help="Where to save the trained model")
    parser.add_argument("--tune", action="store_true",
                         help="Grid-search hyperparameters instead of using the pre-tuned defaults")
    args = parser.parse_args()

    train(args.data_dir, args.model_out, tune=args.tune)


if __name__ == "__main__":
    sys.exit(main())
