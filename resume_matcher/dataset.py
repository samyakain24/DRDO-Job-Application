"""
dataset.py
----------
Builds the training dataset for the job-role matcher.

Expected folder layout (one sub-folder per job role, each containing one
PDF per job posting for that role):

    <data_dir>/
        AIML jobs/
            Accenture.pdf
            Turing.pdf
            ...
        Full stack jobs/
            ...
        Software engineer jobs/
            ...
        data analyst jobs/
            ...
        python jobs/
            ...

Each PDF becomes one labeled training example: (requirements_text, role_name).
"""

import os
from dataclasses import dataclass
from typing import List

from pdf_utils import extract_text_from_pdf


@dataclass
class Example:
    text: str
    label: str
    source_file: str


def load_job_role_dataset(data_dir: str) -> List[Example]:
    """Walk every job-role sub-folder under data_dir and extract training examples."""
    examples: List[Example] = []

    role_folders = sorted(
        d for d in os.listdir(data_dir)
        if os.path.isdir(os.path.join(data_dir, d)) and d.lower().endswith("jobs")
    )

    if not role_folders:
        raise ValueError(f"No job-role folders found under {data_dir!r}")

    for role in role_folders:
        role_path = os.path.join(data_dir, role)
        pdf_files = sorted(f for f in os.listdir(role_path) if f.lower().endswith(".pdf"))

        for pdf_file in pdf_files:
            pdf_path = os.path.join(role_path, pdf_file)
            try:
                text = extract_text_from_pdf(pdf_path)
            except Exception as exc:  # skip unreadable/corrupt PDFs, don't crash training
                print(f"  [skip] {pdf_path}: {exc}")
                continue

            if len(text.split()) < 5:
                print(f"  [skip] {pdf_path}: too little extractable text")
                continue

            examples.append(Example(text=text, label=role, source_file=pdf_file))

    return examples


def dataset_summary(examples: List[Example]) -> str:
    counts = {}
    for ex in examples:
        counts[ex.label] = counts.get(ex.label, 0) + 1
    lines = [f"  {role:<25s} {n:>3d} postings" for role, n in sorted(counts.items())]
    return "\n".join(lines)
