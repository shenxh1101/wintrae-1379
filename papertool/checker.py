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
                    user_choices: Dict = None,
                    ) -> Dict:
    """
    规划路径一致性修复方案（预演用，不实际修改）。

    Args:
        db: PaperDatabase
        folder: 基础文件夹
        missing_files: 数据库有但文件不存在的路径列表
        unindexed_files: 文件存在但数据库没有的路径列表
        user_choices: 可选，交互式用户选择 {
            "remove": [path, ...],            # 选择移除的 missing 路径
            "redirect": [(old, new), ...],    # 选择重定向的 (old, new)
            "skip_missing": [path, ...],      # 选择跳过的 missing 路径
            "scan": [path, ...],              # 选择扫描入库的未入库文件
        }
        若 user_choices 为 None 则按原有自动策略：唯一匹配就重定向，否则移除。

    Returns:
        dict with keys:
          - remove_records: [(missing_path, paper_title), ...]
          - redirects: [(missing_path, candidate_unindexed_path, reason), ...]
          - scan_files: [unindexed_path, ...]
          - ambiguous: [(missing_path, [candidate1, candidate2, ...]), ...]
          - skipped_missing: [(path, title), ...]  保留不动的失效记录
          - skipped_unindexed: [path, ...]  保留不动的未入库文件
          - candidates: {missing_path: [(candidate, reason), ...]}  所有候选（用于交互）
    """
    def _norm(p):
        return os.path.abspath(os.path.normpath(p))

    folder = _norm(folder)

    # 先收集所有候选（供交互使用）
    all_candidates = {}
    skip_missing_set = set()
    skip_unindexed_set = set()

    remove_chosen = set()
    redirect_chosen = {}  # old_path -> (new_path, reason)
    scan_chosen = set()

    if user_choices:
        for p in user_choices.get("skip_missing", []):
            skip_missing_set.add(_norm(p))
        for p in user_choices.get("remove", []):
            remove_chosen.add(_norm(p))
        for old, new in user_choices.get("redirect", []):
            redirect_chosen[_norm(old)] = (_norm(new), "user_selected")
        for p in user_choices.get("scan", []):
            scan_chosen.add(_norm(p))
        for p in user_choices.get("skip_unindexed", []):
            skip_unindexed_set.add(_norm(p))

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

        all_candidates[miss_norm] = {
            "title": title,
            "candidates": list(candidates),
        }

    # 应用选择 / 自动策略
    remove_records = []
    redirects = []
    ambiguous = []
    skipped_missing = []
    scan_files = []

    used_unindexed = set()

    for miss in missing_files:
        miss_norm = _norm(miss)
        info = all_candidates[miss_norm]
        title = info["title"]
        candidates = info["candidates"]

        if miss_norm in skip_missing_set:
            skipped_missing.append((miss_norm, title))
            continue

        if miss_norm in redirect_chosen:
            new_path, reason = redirect_chosen[miss_norm]
            redirects.append((miss_norm, new_path, reason))
            used_unindexed.add(new_path)
            continue

        if miss_norm in remove_chosen:
            remove_records.append((miss_norm, title))
            continue

        # 自动策略
        if len(candidates) == 1:
            c_path, c_reason = candidates[0]
            redirects.append((miss_norm, c_path, c_reason))
            used_unindexed.add(c_path)
        elif len(candidates) > 1:
            ambiguous.append((miss_norm, [c[0] for c in candidates]))
            remove_records.append((miss_norm, title))
        else:
            remove_records.append((miss_norm, title))

    # 处理未入库文件
    has_scan_whitelist = user_choices is not None and bool(user_choices.get("scan"))
    for u in unindexed_files:
        u_norm = _norm(u)
        if u_norm in skip_unindexed_set:
            continue
        if u_norm in used_unindexed:
            continue
        if has_scan_whitelist:
            if u_norm in scan_chosen:
                scan_files.append(u_norm)
        else:
            scan_files.append(u_norm)

    skipped_unindexed = [
        _norm(u) for u in unindexed_files
        if _norm(u) not in used_unindexed and _norm(u) not in [_norm(s) for s in scan_files]
    ]

    return {
        "remove_records": remove_records,
        "redirects": redirects,
        "scan_files": scan_files,
        "ambiguous": ambiguous,
        "skipped_missing": skipped_missing,
        "skipped_unindexed": skipped_unindexed,
        "candidates": all_candidates,
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
            scanned = []
            for sp in plan["scan_files"]:
                sp = os.path.abspath(os.path.normpath(sp))
                if db.get_paper(sp):
                    continue
                paper = PaperMetadata(file_path=sp)
                if extract_meta:
                    try:
                        from .pdf_parser import extract_pdf_metadata
                        meta = extract_pdf_metadata(sp)
                        if meta:
                            if meta.get("title") and not paper.title:
                                paper.title = meta["title"]
                            if meta.get("authors") and not paper.authors:
                                paper.authors = meta["authors"]
                            if meta.get("year") and not paper.year:
                                paper.year = meta["year"]
                            if meta.get("subject") and not paper.keywords:
                                paper.keywords = meta["subject"].split(", ")
                    except Exception:
                        pass
                db.add_paper(paper)
                scanned.append(sp)
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
