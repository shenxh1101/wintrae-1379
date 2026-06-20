import os
import shutil
from collections import defaultdict
from typing import List, Dict, Tuple, Optional

from .models import PaperMetadata, PaperDatabase
from .pdf_parser import verify_pdf
from .utils import compute_file_hash


class CheckResult:
    def __init__(self):
        self.duplicates: List[List[PaperMetadata]] = []
        self.missing_metadata: List[Tuple[PaperMetadata, List[str]]] = []
        self.invalid_files: List[Tuple[str, str]] = []
        self.missing_files: List[str] = []
        self.unindexed_files: List[str] = []

    @property
    def has_issues(self) -> bool:
        return bool(self.duplicates or self.missing_metadata or self.invalid_files
                    or self.missing_files or self.unindexed_files)

    def summary(self) -> dict:
        return {
            "duplicate_groups": len(self.duplicates),
            "duplicate_count": sum(len(g) - 1 for g in self.duplicates),
            "missing_metadata_count": len(self.missing_metadata),
            "invalid_file_count": len(self.invalid_files),
            "missing_files_count": len(self.missing_files),
            "unindexed_files_count": len(self.unindexed_files),
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


def check_path_consistency(db: PaperDatabase, folder: str,
                           recursive: bool = True) -> Tuple[List[str], List[str]]:
    """
    检查数据库路径与文件系统一致性。

    Returns:
        (missing_files, unindexed_files)
        - missing_files: 数据库中有记录但文件系统中不存在的路径
        - unindexed_files: 文件系统中有但数据库中没有记录的 PDF 路径
    """
    missing = []
    db_paths = set()

    def _norm(p):
        return os.path.abspath(os.path.normpath(p))

    for paper in db.all_papers():
        p = _norm(paper.file_path)
        db_paths.add(p)
        if not os.path.exists(p):
            missing.append(p)

    unindexed = []
    folder = _norm(folder)

    if recursive:
        for root, dirs, files in os.walk(folder):
            for fname in files:
                if fname.lower().endswith(".pdf"):
                    fpath = _norm(os.path.join(root, fname))
                    if fpath not in db_paths:
                        unindexed.append(fpath)
    else:
        for fname in os.listdir(folder):
            if fname.lower().endswith(".pdf"):
                fpath = _norm(os.path.join(folder, fname))
                if os.path.isfile(fpath) and fpath not in db_paths:
                    unindexed.append(fpath)

    return sorted(missing), sorted(unindexed)


def run_full_check(db: PaperDatabase, folder: str = None, recursive: bool = True) -> CheckResult:
    result = CheckResult()

    result.duplicates = check_duplicates(db, by="hash")
    if not result.duplicates:
        result.duplicates = check_duplicates(db, by="doi")

    result.missing_metadata = check_missing_metadata(db)

    if folder and os.path.isdir(folder):
        result.invalid_files = check_invalid_files(folder, recursive)
        result.missing_files, result.unindexed_files = check_path_consistency(db, folder, recursive)

    return result


def plan_path_fixes(db: PaperDatabase, folder: str,
                    missing_files: List[str],
                    unindexed_files: List[str],
                    ) -> Dict:
    """
    规划路径一致性修复方案（预演用，不实际修改）。

    Returns:
        dict with keys:
          - remove_records: [(missing_path, paper_title), ...]  要从数据库移除的记录
          - redirects: [(missing_path, candidate_unindexed_path, reason), ...]  重定向建议
          - scan_files: [unindexed_path, ...]  要扫描入库的文件
          - ambiguous: [(missing_path, [candidate1, candidate2, ...]), ...]  无法确定的歧义
    """
    def _norm(p):
        return os.path.abspath(os.path.normpath(p))

    folder = _norm(folder)

    remove_records = []
    redirects = []
    ambiguous = []
    scan_files = list(unindexed_files)

    unindexed_set = set(_norm(p) for p in unindexed_files)

    for miss in missing_files:
        miss_norm = _norm(miss)
        paper = db.get_paper(miss_norm)
        title = paper.title if paper else os.path.basename(miss_norm)

        candidates = []

        miss_fname = os.path.basename(miss_norm).lower()
        miss_hash = paper.file_hash if paper else None

        for u in unindexed_files:
            u_norm = _norm(u)
            u_fname = os.path.basename(u_norm).lower()

            reasons = []
            if u_fname == miss_fname:
                reasons.append("文件名完全匹配")

            if miss_hash:
                try:
                    u_hash = compute_file_hash(u_norm)
                    if u_hash == miss_hash:
                        reasons.append("文件哈希匹配")
                except Exception:
                    pass

            if reasons:
                candidates.append((u_norm, "; ".join(reasons)))

        if len(candidates) == 1:
            c_path, c_reason = candidates[0]
            redirects.append((miss_norm, c_path, c_reason))
            if c_path in unindexed_set:
                unindexed_set.discard(c_path)
                if c_path in scan_files:
                    scan_files.remove(c_path)
        elif len(candidates) > 1:
            ambiguous.append((miss_norm, [c[0] for c in candidates]))
            remove_records.append((miss_norm, title))
        else:
            remove_records.append((miss_norm, title))

    scan_files_final = [p for p in unindexed_files if _norm(p) in unindexed_set]

    return {
        "remove_records": remove_records,
        "redirects": redirects,
        "scan_files": scan_files_final,
        "ambiguous": ambiguous,
    }


def apply_path_fixes(db: PaperDatabase,
                     plan: Dict,
                     folder: str,
                     extract_meta: bool = True,
                     ) -> Dict:
    """
    实际执行路径修复方案。

    Returns:
        dict with keys:
          - removed: [path, ...]
          - redirected: [(old_path, new_path), ...]
          - scanned: [path, ...]
          - errors: [msg, ...]
          - operations_log: [(op_type, details), ...]  用于 rollback 记录
    """
    from .manager import scan_folder
    from .utils import now_str

    def _norm(p):
        return os.path.abspath(os.path.normpath(p))

    removed = []
    redirected = []
    scanned = []
    errors = []
    ops_log = []

    for miss_path, title in plan["remove_records"]:
        try:
            paper = db.get_paper(_norm(miss_path))
            if paper:
                old_meta = paper.to_dict()
                db.remove_paper(_norm(miss_path))
                removed.append(miss_path)
                ops_log.append(("remove_record", {"file_path": miss_path, "old_metadata": old_meta}))
            else:
                errors.append(f"记录不存在，无法移除: {miss_path}")
        except Exception as e:
            errors.append(f"移除记录失败 {miss_path}: {e}")

    for old_path, new_path, reason in plan["redirects"]:
        try:
            old_norm = _norm(old_path)
            new_norm = _norm(new_path)
            paper = db.get_paper(old_norm)
            if paper:
                old_meta = paper.to_dict()
                db.remove_paper(old_norm)
                paper.file_path = new_norm
                paper.modified_at = now_str()
                db.add_paper(paper)
                redirected.append((old_path, new_path))
                ops_log.append(("redirect_path", {
                    "old_path": old_path,
                    "new_path": new_path,
                    "old_metadata": old_meta,
                    "reason": reason,
                }))
            else:
                errors.append(f"重定向失败（源记录不存在）: {old_path}")
        except Exception as e:
            errors.append(f"重定向失败 {old_path}→{new_path}: {e}")

    if plan["scan_files"]:
        try:
            _, new_count = scan_folder(folder, recursive=True,
                                       extract_meta=extract_meta, db=db)
            scanned = list(plan["scan_files"])
            for sp in scanned:
                ops_log.append(("scan_record", {"file_path": sp}))
        except Exception as e:
            errors.append(f"扫描未入库文件失败: {e}")

    return {
        "removed": removed,
        "redirected": redirected,
        "scanned": scanned,
        "errors": errors,
        "operations_log": ops_log,
    }
