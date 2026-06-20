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
    layers: List[str] = None,
) -> Tuple[List[Tuple[str, str]], List[str]]:
    """
    按层级将论文移动到子文件夹。

    Args:
        db: 论文数据库
        base_dir: 根目录
        dry_run: 是否预演
        layers: 目录层级列表，如 ["topic", "year", "read_status"]
                支持的值: topic, year, read_status
                默认 ["topic"]
    """
    if layers is None:
        layers = ["topic"]

    moved = []
    errors = []

    valid_layers = {"topic", "year", "read_status"}
    layers = [l for l in layers if l in valid_layers]
    if not layers:
        layers = ["topic"]

    for paper in db.all_papers():
        path_parts = []
        for layer in layers:
            if layer == "topic":
                if not paper.topic:
                    break
                path_parts.append(paper.topic)
            elif layer == "year":
                path_parts.append(str(paper.year) if paper.year else "未知年份")
            elif layer == "read_status":
                path_parts.append(paper.read_status or "unknown")

        if not path_parts:
            continue

        safe_parts = []
        for part in path_parts:
            safe = "".join(c for c in part if c not in '<>:"/\\|?*').strip()
            if safe:
                safe_parts.append(safe)

        if not safe_parts:
            continue

        target_dir = os.path.join(base_dir, *safe_parts)
        old_path = paper.file_path
        new_path = os.path.join(target_dir, os.path.basename(old_path))

        if old_path == new_path:
            continue

        if not dry_run:
            try:
                os.makedirs(target_dir, exist_ok=True)
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


def _normalize_doi(v: str) -> str:
    """归一化 DOI：支持 https://doi.org/ 前缀，去除空格，统一小写。"""
    if not v:
        return ""
    v = v.strip()
    lower = v.lower()
    if lower.startswith("https://doi.org/"):
        v = v[len("https://doi.org/"):]
    elif lower.startswith("http://doi.org/"):
        v = v[len("http://doi.org/"):]
    elif lower.startswith("doi:"):
        v = v[4:]
    return v.strip().lower()


def import_metadata_from_csv(
    db: PaperDatabase,
    csv_path: str,
    dry_run: bool = False,
    confirm_list_path: str = None,
    base_dir: str = None,
    fuzzy_title: bool = True,
) -> Tuple[List[Tuple[PaperMetadata, dict]], List[str], List[str], List[tuple], str]:
    """
    从 CSV 批量导入元数据，四级兜底匹配：file_path → DOI → 标题 → 文件名。

    额外增强：
    - DOI 支持 URL 格式 (https://doi.org/10.xxx/yyy)
    - file_path 支持相对路径（基于 CSV 所在目录或 base_dir）
    - 标题大小写不敏感 + 模糊包含匹配
    - 歧义匹配时支持导出待确认清单

    Returns:
        (updated_papers, not_found_paths, errors, ambiguous_matches, confirm_list_written)
        confirm_list_written: 若写入歧义清单，返回文件路径；否则空字符串
    """
    import csv

    updated = []
    not_found = []
    errors = []
    ambiguous = []
    confirm_list_written = ""

    field_mapping = {
        "file_path": "file_path",
        "title": "title",
        "authors": "authors",
        "year": "year",
        "doi": "doi",
        "journal": "journal",
        "keywords": "keywords",
        "tags": "tags",
        "topic": "topic",
        "read_status": "read_status",
        "status": "read_status",
    }

    def _norm(p):
        return os.path.abspath(os.path.normpath(p))

    if base_dir is None:
        base_dir = os.path.dirname(os.path.abspath(csv_path))

    def _resolve_path(fp):
        """file_path 归一化：支持相对路径（相对于 CSV 目录或 base_dir）。"""
        if not fp:
            return ""
        fp = fp.strip()
        if fp.startswith("file://"):
            fp = fp[7:]
        if os.path.isabs(fp):
            return _norm(fp)
        # 先尝试相对 base_dir
        try_path = _norm(os.path.join(base_dir, fp))
        if os.path.exists(try_path):
            return try_path
        # 再尝试相对当前目录
        try_path2 = _norm(fp)
        if os.path.exists(try_path2):
            return try_path2
        return _norm(try_path)

    papers_by_path = {}
    papers_by_doi = {}
    papers_by_title_exact = {}
    papers_by_fname = {}
    papers_all = list(db.all_papers())

    for p in papers_all:
        papers_by_path[_norm(p.file_path)] = p
        if p.doi:
            d = _normalize_doi(p.doi)
            if d:
                papers_by_doi.setdefault(d, []).append(p)
        if p.title:
            t = p.title.strip().lower()
            if t:
                papers_by_title_exact.setdefault(t, []).append(p)
        fn = os.path.basename(p.file_path).lower()
        papers_by_fname.setdefault(fn, []).append(p)

    def _fuzzy_title_match(q: str) -> List[PaperMetadata]:
        """标题模糊匹配：去掉停用词后做子串包含。"""
        if not q:
            return []
        q = q.strip().lower()
        candidates = []
        for paper in papers_all:
            t = (paper.title or "").strip().lower()
            if not t:
                continue
            if q == t or q in t or t in q:
                candidates.append(paper)
                continue
            q_parts = [s for s in q.split() if len(s) >= 3]
            t_parts = [s for s in t.split() if len(s) >= 3]
            if q_parts and t_parts and len(set(q_parts) & set(t_parts)) >= max(1, len(q_parts) // 2):
                candidates.append(paper)
        return candidates

    rows_data = []

    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows_data = [(row_num, dict(row)) for row_num, row in enumerate(reader, 2)]
    except FileNotFoundError:
        errors.append(f"文件不存在: {csv_path}")
        return updated, not_found, errors, ambiguous, confirm_list_written
    except Exception as e:
        errors.append(f"读取 CSV 失败: {str(e)}")
        return updated, not_found, errors, ambiguous, confirm_list_written

    # 第一阶段：收集所有候选
    resolve_results = []  # (row_num, row, candidates, match_level, match_reason, row_info)

    for row_num, row in rows_data:
        candidates = []
        match_reason = ""
        match_level = 0  # 1 精确, 2 DOI, 3 标题, 4 文件名, 5 模糊

        fp_raw = row.get("file_path", "").strip()
        doi_raw = row.get("doi", "").strip()
        title_raw = row.get("title", "").strip()

        doi_v = _normalize_doi(doi_raw)
        title_v = title_raw.lower() if title_raw else ""
        fp = _resolve_path(fp_raw) if fp_raw else ""

        fn_v = ""
        if fp:
            fn_v = os.path.basename(fp).lower()
        elif fp_raw:
            fn_v = os.path.basename(fp_raw).lower()

        row_info_parts = []
        if fp_raw:
            row_info_parts.append(f"file_path={fp_raw}")
        if doi_raw:
            row_info_parts.append(f"doi={doi_raw}")
        if title_raw:
            row_info_parts.append(f"title={title_raw[:50]}")
        row_info = ", ".join(row_info_parts) or f"第{row_num}行"

        # L1: file_path
        if fp:
            p = papers_by_path.get(fp)
            if p:
                candidates = [p]
                match_level = 1
                match_reason = f"file_path 精确匹配 ({os.path.basename(fp)})"

        # L2: DOI (含 URL)
        if not candidates and doi_v:
            lst = papers_by_doi.get(doi_v, [])
            if lst:
                candidates = lst
                match_level = 2
                match_reason = f"DOI 匹配 ({doi_v})"

        # L3: 标题精确
        if not candidates and title_v:
            lst = papers_by_title_exact.get(title_v, [])
            if lst:
                candidates = lst
                match_level = 3
                match_reason = f"标题精确匹配 ({title_raw[:40]})"

        # L4: 文件名精确
        if not candidates and fn_v:
            lst = papers_by_fname.get(fn_v, [])
            if lst:
                candidates = lst
                match_level = 4
                match_reason = f"文件名匹配 ({fn_v})"

        # L5: 标题模糊（可选）
        if not candidates and fuzzy_title and title_v:
            lst = _fuzzy_title_match(title_v)
            if lst:
                candidates = lst
                match_level = 5
                match_reason = f"标题模糊匹配 ({title_raw[:40]})"

        resolve_results.append((row_num, row, candidates, match_level, match_reason, row_info))

    # 第二阶段：处理歧义
    ambiguous_rows = []
    for row_num, row, candidates, match_level, match_reason, row_info in resolve_results:
        if len(candidates) > 1:
            ambiguous_rows.append((row_num, row, candidates, match_level, match_reason, row_info))
            ambiguous.append((row_num, row_info, candidates))

    # 若有歧义，可导出确认清单
    if ambiguous_rows and confirm_list_path:
        try:
            with open(confirm_list_path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow([
                    "row_num", "row_info", "match_reason", "choice_index",
                    "candidate_index", "candidate_title", "candidate_file_path", "candidate_year", "candidate_doi",
                    "csv_title", "csv_doi", "csv_file_path"
                ])
                for row_num, row, candidates, match_level, match_reason, row_info in ambiguous_rows:
                    for idx, cand in enumerate(candidates):
                        w.writerow([
                            row_num, row_info, match_reason, "",
                            idx,
                            cand.title or "",
                            cand.file_path or "",
                            cand.year or "",
                            cand.doi or "",
                            row.get("title", ""),
                            row.get("doi", ""),
                            row.get("file_path", ""),
                        ])
            confirm_list_written = confirm_list_path
        except Exception as e:
            errors.append(f"写入歧义清单失败: {e}")

    # 第三阶段：更新论文（无歧义的）
    for row_num, row, candidates, match_level, match_reason, row_info in resolve_results:
        matched_paper = None
        if len(candidates) == 1:
            matched_paper = candidates[0]

        if matched_paper is None:
            not_found.append(row_info)
            continue

        old_meta = matched_paper.to_dict()
        new_meta = {}
        skip_row = False

        for csv_col, field in field_mapping.items():
            if csv_col == "file_path" or csv_col not in row:
                continue
            val = row[csv_col].strip()
            if not val:
                continue

            if field in ("authors", "keywords", "tags"):
                items = [s.strip() for s in val.split(";") if s.strip()]
                if items:
                    new_meta[field] = items
            elif field == "year":
                try:
                    new_meta[field] = int(val)
                except (ValueError, TypeError):
                    errors.append(f"第 {row_num} 行: year 必须是整数 ({val!r})")
                    skip_row = True
                    break
            elif field == "doi":
                new_meta[field] = _normalize_doi(val) or val
            else:
                new_meta[field] = val

        if skip_row or not new_meta:
            continue

        if not dry_run:
            for k, v in new_meta.items():
                setattr(matched_paper, k, v)
            from .utils import now_str
            matched_paper.modified_at = now_str()
            db.add_paper(matched_paper)

        new_meta["_match_reason"] = match_reason
        new_meta["_match_level"] = match_level
        updated.append((matched_paper, new_meta, old_meta))

    return updated, not_found, errors, ambiguous, confirm_list_written
