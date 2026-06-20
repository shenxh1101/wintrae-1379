import os
import re
from typing import Tuple, List, Optional

try:
    from PyPDF2 import PdfReader
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False


def extract_pdf_metadata(file_path: str) -> dict:
    result = {
        "title": None,
        "authors": [],
        "year": None,
        "doi": None,
        "subject": None,
        "keywords": [],
        "valid": True,
    }

    if not PYPDF_AVAILABLE:
        return result

    try:
        reader = PdfReader(file_path)
        info = reader.metadata

        if info:
            if info.title:
                result["title"] = str(info.title).strip() or None
            if info.author:
                author_str = str(info.author).strip()
                if author_str:
                    result["authors"] = _parse_authors(author_str)
            if info.subject:
                result["subject"] = str(info.subject).strip() or None
            if info.keywords:
                kw_str = str(info.keywords).strip()
                if kw_str:
                    result["keywords"] = [
                        k.strip() for k in re.split(r"[,;]", kw_str) if k.strip()
                    ]

        first_page_text = ""
        try:
            if len(reader.pages) > 0:
                first_page_text = reader.pages[0].extract_text() or ""
        except Exception:
            pass

        if first_page_text:
            doi = _extract_doi(first_page_text)
            if doi and not result["doi"]:
                result["doi"] = doi

            if not result["title"]:
                title = _guess_title_from_text(first_page_text)
                if title:
                    result["title"] = title

            year = _extract_year(first_page_text)
            if year and not result["year"]:
                result["year"] = year

            if not result["authors"]:
                authors = _guess_authors_from_text(first_page_text)
                if authors:
                    result["authors"] = authors

    except Exception:
        result["valid"] = False

    return result


def parse_filename_for_metadata(filename: str) -> dict:
    result = {
        "title": None,
        "authors": [],
        "year": None,
        "doi": None,
    }

    base = os.path.splitext(filename)[0]

    year_match = re.search(r"(19|20)\d{2}", base)
    if year_match:
        result["year"] = int(year_match.group())

    doi_match = re.search(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", base, re.IGNORECASE)
    if doi_match:
        result["doi"] = doi_match.group()

    parts = re.split(r"\s*[-–_]\s*", base)
    if len(parts) >= 2:
        cleaned_parts = [p.strip() for p in parts if p.strip()]
        if cleaned_parts:
            if result["year"] and str(result["year"]) == cleaned_parts[0]:
                if len(cleaned_parts) >= 2:
                    result["authors"] = [cleaned_parts[1]]
                    if len(cleaned_parts) > 2:
                        result["title"] = " ".join(cleaned_parts[2:])
            else:
                result["title"] = " ".join(cleaned_parts)

    if not result["title"]:
        result["title"] = base

    return result


def verify_pdf(file_path: str) -> Tuple[bool, str]:
    if not os.path.exists(file_path):
        return False, "File not found"

    if os.path.getsize(file_path) == 0:
        return False, "File is empty"

    if not PYPDF_AVAILABLE:
        try:
            with open(file_path, "rb") as f:
                header = f.read(5)
                if header.startswith(b"%PDF-"):
                    return True, "Valid PDF header"
                else:
                    return False, "Not a valid PDF (invalid header)"
        except IOError as e:
            return False, f"Cannot read file: {e}"

    try:
        reader = PdfReader(file_path)
        num_pages = len(reader.pages)
        if num_pages > 0:
            return True, f"Valid PDF, {num_pages} pages"
        else:
            return False, "PDF has no pages"
    except Exception as e:
        return False, f"Invalid or corrupted PDF: {str(e)}"


def _parse_authors(author_str: str) -> List[str]:
    if not author_str:
        return []
    authors = re.split(r"[;,]| and ", author_str)
    return [a.strip() for a in authors if a.strip()]


def _extract_doi(text: str) -> Optional[str]:
    doi_pattern = r"10\.\d{4,9}/[-._;()/:A-Z0-9]+"
    match = re.search(doi_pattern, text, re.IGNORECASE)
    if match:
        doi = match.group().rstrip(".,;")
        return doi
    return None


def _extract_year(text: str) -> Optional[int]:
    year_pattern = r"\b(19|20)\d{2}\b"
    match = re.search(year_pattern, text)
    if match:
        return int(match.group())
    return None


def _guess_title_from_text(text: str, max_lines: int = 10) -> Optional[str]:
    lines = text.strip().split("\n")
    candidates = []
    for line in lines[:max_lines]:
        line = line.strip()
        if len(line) > 10 and not line.startswith(("http://", "https://", "doi:", "DOI:")):
            if not re.match(r"^[\d\s]+$", line):
                candidates.append(line)

    if candidates:
        best = max(candidates, key=lambda x: (len(x.split()) > 3, len(x)))
        if len(best) > 10:
            return best[:200]
    return None


def _guess_authors_from_text(text: str) -> List[str]:
    lines = text.strip().split("\n")
    for line in lines[:15]:
        line = line.strip()
        if re.match(r"^[A-Z][a-z]+(\s+[A-Z][a-z]+)+(\s*,|\s+and\s+)", line):
            authors = _parse_authors(line)
            if 1 <= len(authors) <= 10:
                return authors
    return []
