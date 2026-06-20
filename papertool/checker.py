import os
from collections import defaultdict
from typing import List, Dict, Tuple

from .models import PaperMetadata, PaperDatabase
from .pdf_parser import verify_pdf
from .utils import compute_file_hash


class CheckResult:
    def __init__(self):
        self.duplicates: List[List[PaperMetadata]] = []
        self.missing_metadata: List[Tuple[PaperMetadata, List[str]]] = []
        self.invalid_files: List[Tuple[str, str]] = []

    @property
    def has_issues(self) -> bool:
        return bool(self.duplicates or self.missing_metadata or self.invalid_files)

    def summary(self) -> dict:
        return {
            "duplicate_groups": len(self.duplicates),
            "duplicate_count": sum(len(g) - 1 for g in self.duplicates),
            "missing_metadata_count": len(self.missing_metadata),
            "invalid_file_count": len(self.invalid_files),
        }


def check_duplicates(db: PaperDatabase, by: str = "hash") -> List[List[PaperMetadata]]:
    groups = defaultdict(list)

    for paper in db.all_papers():
        if by == "hash" and paper.file_hash:
            key = paper.file_hash
        elif by == "doi" and paper.doi:
            key = paper.doi.lower()
        elif by == "title" and paper.title:
            key = paper.title.lower().strip()
        else:
            continue
        groups[key].append(paper)

    duplicates = [g for g in groups.values() if len(g) > 1]
    duplicates.sort(key=lambda g: len(g), reverse=True)
    return duplicates


def check_missing_metadata(db: PaperDatabase, required_fields: List[str] = None) -> List[Tuple[PaperMetadata, List[str]]]:
    if required_fields is None:
        required_fields = ["title", "authors", "year"]

    results = []
    for paper in db.all_papers():
        missing = []
        for field in required_fields:
            value = getattr(paper, field, None)
            if value is None or value == "" or (isinstance(value, list) and len(value) == 0):
                missing.append(field)
        if missing:
            results.append((paper, missing))

    results.sort(key=lambda x: len(x[1]), reverse=True)
    return results


def check_invalid_files(folder: str, recursive: bool = True) -> List[Tuple[str, str]]:
    invalid = []

    if recursive:
        for root, dirs, files in os.walk(folder):
            for fname in files:
                if fname.lower().endswith(".pdf"):
                    fpath = os.path.join(root, fname)
                    valid, reason = verify_pdf(fpath)
                    if not valid:
                        invalid.append((fpath, reason))
    else:
        for fname in os.listdir(folder):
            if fname.lower().endswith(".pdf"):
                fpath = os.path.join(folder, fname)
                if os.path.isfile(fpath):
                    valid, reason = verify_pdf(fpath)
                    if not valid:
                        invalid.append((fpath, reason))

    return invalid


def run_full_check(db: PaperDatabase, folder: str = None, recursive: bool = True) -> CheckResult:
    result = CheckResult()

    result.duplicates = check_duplicates(db, by="hash")
    if not result.duplicates:
        result.duplicates = check_duplicates(db, by="doi")

    result.missing_metadata = check_missing_metadata(db)

    if folder and os.path.isdir(folder):
        result.invalid_files = check_invalid_files(folder, recursive)

    return result
