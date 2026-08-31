import pdfplumber
from docx import Document


def extract_resume_text(file_path: str, content_type: str) -> str:
    if content_type == "application/pdf":
        with pdfplumber.open(file_path) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    doc = Document(file_path)
    return "\n".join(p.text for p in doc.paragraphs)
