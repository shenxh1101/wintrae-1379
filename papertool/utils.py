import hashlib
import os
import re
from datetime import datetime
from typing import Optional


def sanitize_filename(name: str, max_length: int = 150) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name)
    name = name.strip().strip(".")
    name = re.sub(r"\s+", " ", name)
    if len(name) > max_length:
        name = name[:max_length].rstrip()
    return name


def generate_filename(
    title: str = None,
    authors: list = None,
    year: int = None,
    extension: str = ".pdf",
) -> str:
    parts = []
    if year:
        parts.append(str(year))
    if authors:
        first_author = authors[0].split(",")[0].strip()
        first_author = first_author.split()[-1] if first_author else ""
        if len(authors) > 1:
            parts.append(f"{first_author}_et_al")
        else:
            parts.append(first_author)
    if title:
        short_title = title[:80]
        parts.append(short_title)
    filename = " - ".join(filter(None, parts))
    filename = sanitize_filename(filename)
    if not filename:
        filename = "untitled"
    return filename + extension


def compute_file_hash(file_path: str, chunk_size: int = 8192) -> str:
    md5 = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                md5.update(chunk)
        return md5.hexdigest()
    except IOError:
        return ""


def get_file_size(file_path: str) -> int:
    try:
        return os.path.getsize(file_path)
    except OSError:
        return 0


def format_file_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


def now_str() -> str:
    return datetime.now().isoformat(timespec="seconds")


def parse_date(date_str: str) -> Optional[datetime]:
    for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%Y", "%B %Y", "%b %Y"]:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None
