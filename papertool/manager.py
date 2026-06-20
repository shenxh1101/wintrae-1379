import os
import shutil
from typing import List, Tuple, Callable, Optional

from .models import PaperMetadata, PaperDatabase
from .pdf_parser import extract_pdf_metadata, parse_filename_for_metadata, verify_pdf
from .utils import (
    compute_file_hash,
    generate_filename,
    get_file_size,
    now_str,
)


def _normalize_path(path: str) -> str:
    return os.path.abspath(os.path.normpath(path))


def scan_folder(
    folder: str,
    recursive: bool = True,
    extract_meta: bool = True,
    db: PaperDatabase = None,
) -> Tuple[PaperDatabase, int]:
    if db is None:
        db = PaperDatabase()

    count = 0
    files = []
    folder = _normalize_path(folder)

    if recursive:
        for root, dirs, filenames in os.walk(folder):
            for fname in filenames:
                if fname.lower().endswith(".pdf"):
                    files.append(_normalize_path(os.path.join(root, fname)))
    else:
        for fname in os.listdir(folder):
            if fname.lower().endswith(".pdf"):
                fpath = _normalize_path(os.path.join(folder, fname))
                if os.path.isfile(fpath):
                    files.append(fpath)

    for fpath in files:
        if fpath in db.papers:
            continue

        paper = PaperMetadata(file_path=fpath)
        paper.file_size = get_file_size(fpath)
        paper.added_at = now_str()
        paper.modified_at = now_str()

        try:
            paper.file_hash = compute_file_hash(fpath)
        except Exception:
            pass

        if extract_meta:
            pdf_meta = extract_pdf_metadata(fpath)
            if pdf_meta.get("title"):
                paper.title = pdf_meta["title"]
            if pdf_meta.get("authors"):
                paper.authors = pdf_meta["authors"]
            if pdf_meta.get("year"):
                paper.year = pdf_meta["year"]
            if pdf_meta.get("doi"):
                paper.doi = pdf_meta["doi"]
            if pdf_meta.get("subject"):
                paper.journal = pdf_meta["subject"]
            if pdf_meta.get("keywords"):
                paper.keywords = pdf_meta["keywords"]

        if not paper.title:
            name_meta = parse_filename_for_metadata(os.path.basename(fpath))
            if not paper.title and name_meta.get("title"):
                paper.title = name_meta["title"]
            if not paper.authors and name_meta.get("authors"):
                paper.authors = name_meta["authors"]
            if not paper.year and name_meta.get("year"):
                paper.year = name_meta["year"]
            if not paper.doi and name_meta.get("doi"):
                paper.doi = name_meta["doi"]

        db.add_paper(paper)
        count += 1

    return db, count


def rename_papers(
    db: PaperDatabase,
    paper_paths: List[str] = None,
    dry_run: bool = False,
    conflict_strategy: str = "prompt",
) -> Tuple[List[Tuple[str, str]], List[str]]:
    renamed = []
    conflicts = []

    if paper_paths is None:
        paper_paths = list(db.papers.keys())

    for old_path in paper_paths:
        paper = db.get_paper(old_path)
        if not paper:
            continue

        new_name = generate_filename(
            title=paper.title,
            authors=paper.authors,
            year=paper.year,
        )

        dir_name = os.path.dirname(old_path)
        new_path = os.path.join(dir_name, new_name)

        if new_path == old_path:
            continue

        if os.path.exists(new_path):
            conflicts.append((old_path, new_path))
            if conflict_strategy == "skip":
                continue
            elif conflict_strategy == "overwrite":
                pass
            elif conflict_strategy == "suffix":
                base, ext = os.path.splitext(new_path)
                i = 1
                while os.path.exists(f"{base}_{i}{ext}"):
                    i += 1
                new_path = f"{base}_{i}{ext}"

        if not dry_run:
            try:
                os.rename(old_path, new_path)
                db.remove_paper(old_path)
                paper.file_path = new_path
                paper.modified_at = now_str()
                db.add_paper(paper)
                renamed.append((old_path, new_path))
            except OSError as e:
                conflicts.append((old_path, str(e)))
        else:
            renamed.append((old_path, new_path))

    return renamed, conflicts


def move_by_topic(
    db: PaperDatabase,
    base_dir: str,
    dry_run: bool = False,
) -> Tuple[List[Tuple[str, str]], List[str]]:
    moved = []
    errors = []

    for paper in db.all_papers():
        if not paper.topic:
            continue

        topic_dir = os.path.join(base_dir, paper.topic)
        old_path = paper.file_path
        new_path = os.path.join(topic_dir, os.path.basename(old_path))

        if old_path == new_path:
            continue

        if not dry_run:
            try:
                os.makedirs(topic_dir, exist_ok=True)
                shutil.move(old_path, new_path)
                db.remove_paper(old_path)
                paper.file_path = new_path
                paper.modified_at = now_str()
                db.add_paper(paper)
                moved.append((old_path, new_path))
            except (OSError, shutil.Error) as e:
                errors.append(f"{old_path}: {str(e)}")
        else:
            moved.append((old_path, new_path))

    return moved, errors


def update_paper_metadata(
    db: PaperDatabase,
    file_path: str,
    **kwargs,
) -> Optional[PaperMetadata]:
    paper = db.get_paper(file_path)
    if not paper:
        return None

    for key, value in kwargs.items():
        if hasattr(paper, key):
            setattr(paper, key, value)

    paper.modified_at = now_str()
    db.add_paper(paper)
    return paper


def add_tags(db: PaperDatabase, file_path: str, tags: List[str]) -> Optional[PaperMetadata]:
    paper = db.get_paper(file_path)
    if not paper:
        return None

    for tag in tags:
        if tag not in paper.tags:
            paper.tags.append(tag)

    paper.modified_at = now_str()
    db.add_paper(paper)
    return paper


def remove_tags(db: PaperDatabase, file_path: str, tags: List[str]) -> Optional[PaperMetadata]:
    paper = db.get_paper(file_path)
    if not paper:
        return None

    paper.tags = [t for t in paper.tags if t not in tags]
    paper.modified_at = now_str()
    db.add_paper(paper)
    return paper


def set_read_status(
    db: PaperDatabase,
    file_path: str,
    status: str,
) -> Optional[PaperMetadata]:
    paper = db.get_paper(file_path)
    if not paper:
        return None

    paper.read_status = status
    paper.modified_at = now_str()
    db.add_paper(paper)
    return paper


def find_papers(
    db: PaperDatabase,
    title: str = None,
    author: str = None,
    tags: List[str] = None,
    topic: str = None,
    read_status: str = None,
    year: int = None,
) -> List[PaperMetadata]:
    results = []
    for paper in db.all_papers():
        if title and title.lower() not in (paper.title or "").lower():
            continue
        if author and not any(author.lower() in a.lower() for a in paper.authors):
            continue
        if tags and not all(t in paper.tags for t in tags):
            continue
        if topic and (paper.topic or "") != topic:
            continue
        if read_status and paper.read_status != read_status:
            continue
        if year and paper.year != year:
            continue
        results.append(paper)
    return results
