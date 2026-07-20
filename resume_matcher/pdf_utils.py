"""
pdf_utils.py
------------
Helper functions for pulling plain text out of PDF files (job postings and
resumes) so it can be fed into the ML pipeline.
"""

import pypdf


def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract and lightly clean all text from a single PDF file."""
    text_parts = []
    with open(pdf_path, "rb") as f:
        reader = pypdf.PdfReader(f)
        for page in reader.pages:
            page_text = page.extract_text() or ""
            text_parts.append(page_text)

    text = "\n".join(text_parts)

    # Light cleanup: collapse excess whitespace, drop lone bullet characters.
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln and ln not in {"•", "-", "*"}]
    return " ".join(lines)
