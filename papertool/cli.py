import os
import sys

import click

from .__init__ import __version__
from .models import PaperDatabase, PaperMetadata
from .manager import (
    scan_folder as _scan_folder,
    rename_papers as _rename_papers,
    move_by_topic as _move_by_topic,
    update_paper_metadata as _update_paper_metadata,
    add_tags as _add_tags_to_paper,
    remove_tags as _remove_tags_from_paper,
    set_read_status as _set_paper_read_status,
    find_papers as _find_papers,
    import_metadata_from_csv as _import_metadata_from_csv,
)
from .exporter import export_bibtex, export_csv, export_reading_list
from .checker import check_duplicates, check_missing_metadata, check_invalid_files, check_path_consistency, plan_path_fixes, apply_path_fixes
from .operations import RollbackManager
from .utils import format_file_size


DEFAULT_DB_PATH = os.path.join(os.path.expanduser("~"), ".papertool", "papers.json")
DEFAULT_LOG_DIR = os.path.join(os.path.expanduser("~"), ".papertool", "logs")


def get_db_path(ctx):
    return ctx.obj["db_path"]


def load_db(ctx):
    return PaperDatabase.load(get_db_path(ctx))


def save_db(ctx, db):
    db.save(get_db_path(ctx))


def get_rollback(ctx):
    log_dir = ctx.obj.get("log_dir", DEFAULT_LOG_DIR)
    return RollbackManager(log_dir)


def _norm_path(p):
    return os.path.abspath(os.path.normpath(p))


@click.group()
@click.version_option(__version__, prog_name="papertool")
@click.option("--db-path", default=DEFAULT_DB_PATH, help="数据库文件路径")
@click.option("--log-dir", default=DEFAULT_LOG_DIR, help="日志目录路径")
@click.pass_context
def cli(ctx, db_path, log_dir):
    """科研助理文献整理工具 - 批量管理 PDF 文献与引用信息"""
    ctx.ensure_object(dict)
    ctx.obj["db_path"] = db_path
    ctx.obj["log_dir"] = log_dir


@cli.command()
@click.argument("folder", type=click.Path(exists=True, file_okay=False))
@click.option("--recursive/--no-recursive", default=True, help="是否递归扫描子文件夹")
@click.option("--extract-meta/--no-extract-meta", default=True, help="是否从 PDF 提取元数据")
@click.option("--dry-run", is_flag=True, help="预演模式，不实际修改数据库")
@click.pass_context
def scan(ctx, folder, recursive, extract_meta, dry_run):
    """扫描文件夹中的 PDF 论文，提取元数据并存入数据库"""
    click.echo(f"扫描文件夹: {folder}")
    click.echo(f"递归: {recursive}")
    click.echo()

    db = load_db(ctx)
    initial_count = len(db.all_papers())

    new_db, new_count = _scan_folder(
        folder,
        recursive=recursive,
        extract_meta=extract_meta,
        db=db,
    )

    click.echo(f"扫描完成，共发现 {new_count} 篇新论文")
    click.echo(f"数据库现有 {len(new_db.all_papers())} 篇 (之前有 {initial_count} 篇)")
    click.echo()

    papers = new_db.all_papers()[-new_count:] if new_count > 0 else []
    for i, paper in enumerate(papers[:20], 1):
        title = paper.title or "未知标题"
        authors = ", ".join(paper.authors) if paper.authors else "未知作者"
        year = paper.year or "----"
        size = format_file_size(paper.file_size)
        click.echo(f"  {i}. [{year}] {title}")
        click.echo(f"     作者: {authors}")
        click.echo(f"     文件: {paper.file_path} ({size})")
        click.echo()

    if len(papers) > 20:
        click.echo(f"  ... 还有 {len(papers) - 20} 篇")
        click.echo()

    if not dry_run:
        save_db(ctx, new_db)
        click.echo("数据库已更新")
    else:
        click.echo("(预演模式，未保存)")


@cli.command()
@click.option("--folder", type=click.Path(exists=True, file_okay=False), help="指定文件夹，仅重命名该文件夹内的论文")
@click.option("--all", "all_papers", is_flag=True, help="重命名数据库中所有论文")
@click.option("--dry-run", is_flag=True, help="预演模式，不实际重命名文件")
@click.option("--conflict", type=click.Choice(["prompt", "skip", "overwrite", "suffix"]), default="suffix", help="文件名冲突处理策略")
@click.option("--yes", "-y", is_flag=True, help="跳过确认直接执行")
@click.pass_context
def rename(ctx, folder, all_papers, dry_run, conflict, yes):
    """按标题、作者、年份规范重命名 PDF 文件"""
    db = load_db(ctx)

    if not db.all_papers():
        click.echo("数据库为空，请先使用 scan 命令扫描论文")
        return

    target_paths = None
    if folder:
        abs_folder = _norm_path(folder)
        target_paths = [p for p in db.papers.keys() if p.startswith(abs_folder)]
    elif all_papers:
        target_paths = list(db.papers.keys())
    else:
        click.echo("请指定 --folder 或 --all 参数")
        return

    if not target_paths:
        click.echo("没有找到符合条件的论文")
        return

    click.echo(f"准备重命名 {len(target_paths)} 篇论文...")
    click.echo(f"冲突处理策略: {conflict}")
    if dry_run:
        click.echo("(预演模式)")
    click.echo()

    renamed, conflicts = _rename_papers(
        db,
        paper_paths=target_paths,
        dry_run=True,
        conflict_strategy=conflict,
    )

    if renamed:
        click.echo(f"重命名 {len(renamed)} 个文件:")
        for old, new in renamed[:15]:
            click.echo(f"  {os.path.basename(old)}")
            click.echo(f"    -> {os.path.basename(new)}")
        if len(renamed) > 15:
            click.echo(f"  ... 还有 {len(renamed) - 15} 个")
        click.echo()

    if conflicts:
        click.echo(f"发现 {len(conflicts)} 个冲突/错误:")
        for old, reason in conflicts[:10]:
            click.echo(f"  ! {os.path.basename(old)}: {reason}")
        if len(conflicts) > 10:
            click.echo(f"  ... 还有 {len(conflicts) - 10} 个")
        click.echo()

    if dry_run:
        click.echo("(预演模式，未实际修改)")
        return

    if not renamed:
        click.echo("没有需要重命名的文件")
        return

    if not yes and not click.confirm(f"确认重命名以上 {len(renamed)} 个文件?", default=False):
        click.echo("已取消")
        return

    renamed, conflicts = _rename_papers(
        db,
        paper_paths=target_paths,
        dry_run=False,
        conflict_strategy=conflict,
    )

    if not dry_run and renamed:
        rb = get_rollback(ctx)
        rb.start_batch(f"重命名 {len(renamed)} 个文件")
        for old, new in renamed:
            rb.record_rename(old, new)
        rb.end_batch()
        save_db(ctx, db)
        click.echo(f"已重命名 {len(renamed)} 个文件，操作已记录（可使用 rollback 回滚）")
    elif dry_run:
        click.echo("(预演模式，未实际修改)")


@cli.command()
@click.argument("file_path", type=click.Path(exists=True))
@click.option("--add-tags", "tag_add_list", multiple=True, help="添加标签，可多次指定 (例如: --add-tags nlp --add-tags survey)")
@click.option("--remove-tags", "tag_remove_list", multiple=True, help="移除标签，可多次指定")
@click.option("--topic", help="设置课题分组")
@click.option("--status", type=click.Choice(["unread", "reading", "read", "skimmed"]), help="设置阅读状态")
@click.option("--doi", help="设置 DOI")
@click.option("--journal", help="设置期刊名")
@click.option("--title", help="设置标题")
@click.option("--year", type=int, help="设置年份")
@click.option("--author", "author_list", multiple=True, help="添加作者，可多次指定")
@click.option("--keyword", "keyword_list", multiple=True, help="添加关键词，可多次指定")
@click.option("--notes", help="添加备注")
@click.pass_context
def tag(ctx, file_path, tag_add_list, tag_remove_list, topic, status, doi, journal, title, year, author_list, keyword_list, notes):
    """为论文添加/移除标签，补充元数据和阅读状态"""
    db = load_db(ctx)
    abs_path = _norm_path(file_path)

    paper = db.get_paper(abs_path)
    if not paper:
        click.echo(f"未找到论文: {file_path}")
        click.echo("请先使用 scan 命令扫描该文件")
        return

    old_meta = paper.to_dict()
    changed = False

    if tag_add_list:
        _add_tags_to_paper(db, abs_path, list(tag_add_list))
        click.echo(f"添加标签: {', '.join(tag_add_list)}")
        changed = True

    if tag_remove_list:
        _remove_tags_from_paper(db, abs_path, list(tag_remove_list))
        click.echo(f"移除标签: {', '.join(tag_remove_list)}")
        changed = True

    updates = {}
    if topic is not None:
        updates["topic"] = topic
    if status is not None:
        updates["read_status"] = status
    if doi is not None:
        updates["doi"] = doi
    if journal is not None:
        updates["journal"] = journal
    if title is not None:
        updates["title"] = title
    if year is not None:
        updates["year"] = year
    if author_list:
        updates["authors"] = list(author_list)
    if keyword_list:
        updates["keywords"] = list(keyword_list)
    if notes is not None:
        updates["notes"] = notes

    if updates:
        _update_paper_metadata(db, abs_path, **updates)
        for k, v in updates.items():
            click.echo(f"设置 {k}: {v}")
        changed = True

    if not changed:
        click.echo("未指定任何修改")
        return

    paper = db.get_paper(abs_path)
    click.echo()
    _print_paper_info(paper)

    rb = get_rollback(ctx)
    rb.record_metadata_update(abs_path, old_meta, paper.to_dict())

    save_db(ctx, db)


@cli.command()
@click.option("--base-dir", type=click.Path(file_okay=False), help="课题子文件夹的根目录，默认为当前工作目录")
@click.option("--layer", "layers", multiple=True,
              type=click.Choice(["topic", "year", "read_status"]),
              help="目录层级，可多次指定按顺序组合 (例如: --layer topic --layer year)")
@click.option("--dry-run", is_flag=True, help="预演模式，只显示将要执行的移动，不实际操作")
@click.option("--yes", "-y", is_flag=True, help="跳过确认直接执行")
@click.pass_context
def organize(ctx, base_dir, layers, dry_run, yes):
    """按课题/年份/阅读状态分层整理：将论文移动到对应子文件夹"""
    db = load_db(ctx)

    layer_list = list(layers) if layers else ["topic"]

    papers_to_move = []
    for paper in db.all_papers():
        has_all = True
        for layer in layer_list:
            if layer == "topic" and not paper.topic:
                has_all = False
                break
        if has_all:
            papers_to_move.append(paper)

    if not papers_to_move:
        missing = [l for l in layer_list if l == "topic"]
        if missing:
            click.echo("没有找到已设置课题的论文，请先用 tag --topic <课题名> 为论文设置课题")
        else:
            click.echo("没有找到符合条件的论文")
        return

    if base_dir is None:
        base_dir = os.getcwd()
    base_dir = _norm_path(base_dir)

    click.echo(f"根目录: {base_dir}")
    click.echo(f"目录层级: {' / '.join(layer_list)}")
    click.echo(f"待整理论文: {len(papers_to_move)} 篇")
    if dry_run:
        click.echo("(预演模式，不会实际移动文件)")
    click.echo()

    plan = []
    for paper in papers_to_move:
        path_parts = []
        for layer in layer_list:
            if layer == "topic":
                path_parts.append(paper.topic)
            elif layer == "year":
                path_parts.append(str(paper.year) if paper.year else "未知年份")
            elif layer == "read_status":
                path_parts.append(paper.read_status or "unknown")

        safe_parts = []
        for part in path_parts:
            safe = "".join(c for c in part if c not in '<>:"/\\|?*').strip()
            if safe:
                safe_parts.append(safe)

        if not safe_parts:
            click.echo(f"  ! 跳过非法路径的论文: {paper.file_path}")
            continue

        target_dir = os.path.join(base_dir, *safe_parts)
        target_path = os.path.join(target_dir, os.path.basename(paper.file_path))
        target_path = _norm_path(target_path)
        source_path = _norm_path(paper.file_path)

        if source_path == target_path:
            continue

        if os.path.exists(target_path) and target_path != source_path:
            click.echo(f"  ! 目标文件已存在，跳过: {target_path}")
            continue

        plan.append((paper, source_path, target_path))

    if not plan:
        click.echo("没有需要移动的论文")
        return

    click.echo("移动计划:")
    by_dir = {}
    for paper, src, dst in plan:
        target_dir = os.path.dirname(dst)
        by_dir.setdefault(target_dir, []).append((paper, src, dst))

    for target_dir in sorted(by_dir.keys()):
        items = by_dir[target_dir]
        rel_dir = os.path.relpath(target_dir, base_dir)
        click.echo(f"  [{rel_dir}] ({len(items)} 篇)")
        for paper, src, dst in items:
            click.echo(f"    {os.path.basename(src)}")
    click.echo()

    if not yes and not dry_run:
        if not click.confirm(f"确认移动以上 {len(plan)} 个文件?", default=False):
            click.echo("已取消")
            return

    rb = get_rollback(ctx)
    if not dry_run:
        rb.start_batch(f"按 {'/'.join(layer_list)} 整理 {len(plan)} 个文件")

    moved_count = 0
    failed = []

    for paper, src, dst in plan:
        target_dir = os.path.dirname(dst)
        try:
            if not dry_run:
                os.makedirs(target_dir, exist_ok=True)
                if os.path.exists(dst):
                    failed.append((src, "目标已存在"))
                    continue
                os.rename(src, dst)
                db.remove_paper(src)
                paper.file_path = dst
                from .utils import now_str
                paper.modified_at = now_str()
                db.add_paper(paper)
                rb.record_move(src, dst)
            moved_count += 1
        except OSError as e:
            failed.append((src, str(e)))

    if not dry_run:
        rb.end_batch()
        save_db(ctx, db)

    click.echo()
    if dry_run:
        click.echo(f"预演完成：预计移动 {moved_count} 个文件")
    else:
        click.echo(f"已移动 {moved_count} 个文件")
        if moved_count > 0:
            click.echo("操作已记录，可使用 rollback 回滚")

    if failed:
        click.echo()
        click.echo(f"失败 {len(failed)} 个:")
        for src, reason in failed:
            click.echo(f"  ! {src}: {reason}")


@cli.command("import")
@click.argument("csv_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--dry-run", is_flag=True, help="预演模式，不实际更新数据库")
@click.option("--yes", "-y", is_flag=True, help="跳过确认直接执行")
@click.option("--base-dir", type=click.Path(exists=True, file_okay=False),
              help="相对路径解析的基准目录（默认：CSV 所在目录）")
@click.option("--confirm-list", type=click.Path(), default=None,
              help="歧义匹配时导出待确认清单 CSV（编辑 choice_index 列后再导入）")
@click.option("--no-fuzzy", "no_fuzzy", is_flag=True, help="禁用标题模糊匹配（仅精确匹配）")
@click.pass_context
def import_cmd(ctx, csv_path, dry_run, yes, base_dir, confirm_list, no_fuzzy):
    """从 CSV 批量导入元数据（DOI、期刊、关键词、标签、课题、阅读状态等）

    匹配策略（按优先级）：
      1. file_path（支持绝对/相对路径、file:// 前缀）
      2. DOI（支持 https://doi.org/URL、doi:前缀，大小写不敏感）
      3. 标题精确匹配（大小写不敏感）
      4. 文件名精确匹配
      5. 标题模糊匹配（停用词分词后包含，默认启用）

    一行匹配多篇时，会导出歧义清单到 --confirm-list 指定的 CSV，
    在 choice_index 列填入要选的 candidate_index，保存后再执行 import。
    """
    db = load_db(ctx)

    click.echo(f"CSV 文件: {csv_path}")
    if dry_run:
        click.echo("(预演模式，不会更新数据库)")
    if base_dir:
        click.echo(f"相对路径基准目录: {base_dir}")
    click.echo()

    fuzzy = not no_fuzzy
    updated, not_found, errors, ambiguous, confirm_written = _import_metadata_from_csv(
        db, csv_path, dry_run=True,
        confirm_list_path=confirm_list, base_dir=base_dir, fuzzy_title=fuzzy
    )

    if errors:
        click.echo(f"解析错误 ({len(errors)}):")
        for err in errors[:10]:
            click.echo(f"  ✗ {err}")
        if len(errors) > 10:
            click.echo(f"  ... 还有 {len(errors) - 10} 个")
        click.echo()

    if confirm_written:
        click.echo(f"歧义待确认清单已导出: {confirm_written}")
        click.echo("  → 编辑 choice_index 列（填候选的 candidate_index 值）后再导入")
        click.echo()

    if ambiguous:
        click.echo(f"歧义匹配（一行匹配多篇，已跳过） ({len(ambiguous)}):")
        for row_num, row_info, matches in ambiguous[:10]:
            click.echo(f"  ? 第{row_num}行 {row_info}")
            for mp in matches:
                t = mp.title or "未知标题"
                click.echo(f"      - {mp.file_path}  [{t}]")
        if len(ambiguous) > 10:
            click.echo(f"  ... 还有 {len(ambiguous) - 10} 行")
        click.echo()

    if not_found:
        click.echo(f"未找到匹配的论文 ({len(not_found)}):")
        for p in not_found[:10]:
            click.echo(f"  ? {p}")
        if len(not_found) > 10:
            click.echo(f"  ... 还有 {len(not_found) - 10} 个")
        click.echo()

    if not updated:
        click.echo("没有可更新的论文")
        return

    click.echo(f"将更新 {len(updated)} 篇论文:")
    for i, (paper, new_meta, old_meta) in enumerate(updated[:15], 1):
        reason = new_meta.pop("_match_reason", "")
        match_tag = f" [{reason}]" if reason else ""
        click.echo(f"  {i}. {os.path.basename(paper.file_path)}{match_tag}")
        for k, v in new_meta.items():
            if k.startswith("_"):
                continue
            old_val = old_meta.get(k, "")
            if isinstance(old_val, list):
                old_val = "; ".join(old_val) if old_val else ""
            if isinstance(v, list):
                v = "; ".join(v)
            click.echo(f"     {k}: {old_val} → {v}")
    if len(updated) > 15:
        click.echo(f"  ... 还有 {len(updated) - 15} 篇")
    click.echo()

    if not yes and not dry_run:
        if not click.confirm(f"确认更新以上 {len(updated)} 篇论文?", default=False):
            click.echo("已取消")
            return

    if not dry_run:
        updated_real, not_found_real, errors_real, ambiguous_real, confirm_written2 = _import_metadata_from_csv(
            db, csv_path, dry_run=False,
            confirm_list_path=None, base_dir=base_dir, fuzzy_title=fuzzy
        )

        rb = get_rollback(ctx)
        rb.start_batch(f"从 CSV 导入 {len(updated_real)} 篇元数据")
        for paper, new_meta, old_meta in updated_real:
            nm = {k: v for k, v in new_meta.items() if not k.startswith("_")}
            rb.record_metadata_update(paper.file_path, old_meta, paper.to_dict())
        rb.end_batch()

        save_db(ctx, db)
        click.echo(f"已更新 {len(updated_real)} 篇论文，操作已记录（可使用 rollback 回滚）")

        if ambiguous_real:
            click.echo()
            click.echo(f"跳过歧义匹配 {len(ambiguous_real)} 行，请用 --confirm-list 导出清单后确认")
        if errors_real:
            click.echo()
            click.echo(f"更新时出错 ({len(errors_real)}):")
            for err in errors_real:
                click.echo(f"  ✗ {err}")
    else:
        click.echo("(预演模式，未实际更新)")


@cli.command()
@click.argument("output", type=click.Path())
@click.option("--format", "fmt", type=click.Choice(["bibtex", "csv", "reading"]), default="bibtex", help="导出格式")
@click.option("--topic", help="按课题筛选")
@click.option("--tag", "tag_list", multiple=True, help="按标签筛选，可多次指定 (AND 关系)")
@click.option("--status", type=click.Choice(["unread", "reading", "read", "skimmed"]), help="按阅读状态筛选")
@click.option("--year-from", type=int, help="按起始年份筛选 (包含)")
@click.option("--year-to", type=int, help="按结束年份筛选 (包含)")
@click.option("--group-by", "group_by_list", multiple=True,
              type=click.Choice(["topic", "read_status", "year"]),
              help="阅读书单分组字段，可多次指定按顺序嵌套 (例如: --group-by topic --group-by year)")
@click.option("--summary", is_flag=True, help="包含汇总统计 (按课题/年份/状态 + 待读数量)")
@click.pass_context
def export(ctx, output, fmt, topic, tag_list, status, year_from, year_to, group_by_list, summary):
    """导出文献信息为 BibTeX、CSV 或阅读书单，支持多条件筛选、多字段分组和汇总统计"""
    db = load_db(ctx)

    papers = db.all_papers()

    if topic:
        papers = [p for p in papers if p.topic == topic]
    if tag_list:
        papers = [p for p in papers if all(t in p.tags for t in tag_list)]
    if status:
        papers = [p for p in papers if p.read_status == status]
    if year_from is not None:
        papers = [p for p in papers if p.year is not None and p.year >= year_from]
    if year_to is not None:
        papers = [p for p in papers if p.year is not None and p.year <= year_to]

    if not papers:
        click.echo("没有符合条件的论文")
        return

    filter_desc = []
    if topic:
        filter_desc.append(f"topic={topic}")
    if tag_list:
        filter_desc.append(f"tags=[{', '.join(tag_list)}]")
    if status:
        filter_desc.append(f"status={status}")
    if year_from is not None or year_to is not None:
        yf = year_from or "..."
        yt = year_to or "..."
        filter_desc.append(f"year={yf}-{yt}")

    click.echo(f"准备导出 {len(papers)} 篇论文" + (f" (筛选: {', '.join(filter_desc)})" if filter_desc else ""))

    group_by = list(group_by_list) if group_by_list else ["topic"]

    count = 0
    if fmt == "bibtex":
        count = export_bibtex(papers, output)
        click.echo(f"BibTeX 已导出到: {output}")
    elif fmt == "csv":
        count = export_csv(papers, output, include_summary=summary)
        click.echo(f"CSV 已导出到: {output}" + (" (含汇总统计)" if summary else ""))
    elif fmt == "reading":
        count = export_reading_list(papers, output, group_by, include_summary=summary)
        click.echo(f"阅读书单已导出到: {output} (按 {'/'.join(group_by)} 分组)" + (" (含汇总统计)" if summary else ""))

    click.echo(f"共 {count} 条记录")


@cli.command()
@click.option("--folder", type=click.Path(exists=True, file_okay=False), help="指定文件夹检查")
@click.option("--check-type", type=click.Choice(["all", "duplicates", "missing", "invalid", "paths"]), default="all", help="检查类型")
@click.option("--recursive/--no-recursive", default=True, help="是否递归检查")
@click.option("--fix", "fix_paths", is_flag=True, help="修复路径一致性（需配合 --folder 使用）")
@click.option("--dry-run", is_flag=True, help="修复预演，不实际修改")
@click.option("--yes", "-y", is_flag=True, help="跳过确认直接修复")
@click.option("--skip-missing", "skip_missing", multiple=True,
              help="修复时跳过指定失效路径（可多次指定）")
@click.option("--skip-unindexed", "skip_unindexed", multiple=True,
              help="修复时跳过指定未入库文件（可多次指定）")
@click.option("--recheck/--no-recheck", default=True, help="修复后再次检查显示处理情况")
@click.pass_context
def check(ctx, folder, check_type, recursive, fix_paths, dry_run, yes,
          skip_missing, skip_unindexed, recheck):
    """检查重复文献、缺失元数据、损坏文件和路径一致性，支持一键修复与部分跳过"""
    db = load_db(ctx)

    if not db.all_papers():
        click.echo("数据库为空，请先使用 scan 命令扫描论文")
        return

    click.echo(f"数据库中共有 {len(db.all_papers())} 篇论文")
    click.echo()

    if check_type in ("all", "duplicates"):
        click.echo("=== 重复文献检查 ===")
        dupes = check_duplicates(db, by="hash")
        if not dupes:
            dupes = check_duplicates(db, by="doi")
        if dupes:
            click.echo(f"发现 {len(dupes)} 组重复:")
            for i, group in enumerate(dupes[:5], 1):
                click.echo(f"  第 {i} 组 ({len(group)} 篇):")
                for paper in group:
                    t = paper.title or "未知标题"
                    click.echo(f"    - {os.path.basename(paper.file_path)}: {t}")
            if len(dupes) > 5:
                click.echo(f"  ... 还有 {len(dupes) - 5} 组")
            click.echo("  修复建议: 手动删除重复文件后重新 scan")
        else:
            click.echo("未发现重复文献 ✓")
        click.echo()

    if check_type in ("all", "missing"):
        click.echo("=== 缺失元数据检查 ===")
        missing = check_missing_metadata(db)
        if missing:
            click.echo(f"发现 {len(missing)} 篇论文缺少元数据:")
            for paper, fields in missing[:10]:
                fname = os.path.basename(paper.file_path)
                click.echo(f"  ! {fname}: 缺少 {', '.join(fields)}")
            if len(missing) > 10:
                click.echo(f"  ... 还有 {len(missing) - 10} 篇")
            click.echo("  修复建议: 用 tag 命令补充，或 export CSV 批量编辑后 import")
        else:
            click.echo("所有论文元数据完整 ✓")
        click.echo()

    if check_type in ("all", "invalid") and folder:
        click.echo("=== 损坏文件检查 ===")
        invalid = check_invalid_files(folder, recursive)
        if invalid:
            click.echo(f"发现 {len(invalid)} 个损坏/不可打开的文件:")
            for fpath, reason in invalid[:10]:
                click.echo(f"  ✗ {fpath}: {reason}")
            if len(invalid) > 10:
                click.echo(f"  ... 还有 {len(invalid) - 10} 个")
        else:
            click.echo("所有文件都可以正常打开 ✓")
        click.echo()

    missing_files = []
    unindexed_files = []
    if (check_type in ("all", "paths") or fix_paths) and folder:
        click.echo("=== 路径一致性检查 ===")
        missing_files, unindexed_files = check_path_consistency(db, folder, recursive)

        if missing_files:
            click.echo(f"数据库记录但文件不存在 ({len(missing_files)}):")
            for p in missing_files[:10]:
                click.echo(f"  ✗ {p}")
            if len(missing_files) > 10:
                click.echo(f"  ... 还有 {len(missing_files) - 10} 个")
            click.echo()

        if unindexed_files:
            click.echo(f"文件存在但未加入数据库 ({len(unindexed_files)}):")
            for p in unindexed_files[:10]:
                click.echo(f"  ? {p}")
            if len(unindexed_files) > 10:
                click.echo(f"  ... 还有 {len(unindexed_files) - 10} 个")
            click.echo()

        if not missing_files and not unindexed_files:
            click.echo("数据库与文件系统路径完全一致 ✓")
            click.echo()

    if fix_paths and folder:
        before_missing = set(os.path.abspath(os.path.normpath(p)) for p in missing_files)
        before_unindexed = set(os.path.abspath(os.path.normpath(p)) for p in unindexed_files)

        if not missing_files and not unindexed_files:
            click.echo("没有需要修复的路径问题 ✓")
        else:
            def _norm(p):
                return os.path.abspath(os.path.normpath(p))

            skip_missing_set = set(_norm(p) for p in skip_missing)
            skip_unindexed_set = set(_norm(p) for p in skip_unindexed)
            user_choices = {
                "skip_missing": list(skip_missing_set),
                "skip_unindexed": list(skip_unindexed_set),
            }
            plan = plan_path_fixes(db, folder, missing_files, unindexed_files, user_choices)

            click.echo("=== 路径修复方案 ===")
            if dry_run:
                click.echo("(预演模式，不会实际修改)")
            click.echo()

            if plan["skipped_missing"]:
                click.echo(f"保留不动的失效记录 ({len(plan['skipped_missing'])}):")
                for path, title in plan["skipped_missing"][:10]:
                    click.echo(f"  ⏭ 跳过 {os.path.basename(path)}  [{title}]")
                if len(plan["skipped_missing"]) > 10:
                    click.echo(f"  ... 还有 {len(plan['skipped_missing']) - 10} 个")
                click.echo()

            if plan["redirects"]:
                click.echo(f"重定向到现有 PDF ({len(plan['redirects'])}):")
                for old, new, reason in plan["redirects"][:10]:
                    click.echo(f"  ↔ {os.path.basename(old)} → {os.path.basename(new)}  ({reason})")
                if len(plan["redirects"]) > 10:
                    click.echo(f"  ... 还有 {len(plan['redirects']) - 10} 个")
                click.echo()

            if plan["remove_records"]:
                click.echo(f"从数据库移除失效记录 ({len(plan['remove_records'])}):")
                for path, title in plan["remove_records"][:10]:
                    click.echo(f"  ✗ {os.path.basename(path)}  [{title}]")
                if len(plan["remove_records"]) > 10:
                    click.echo(f"  ... 还有 {len(plan['remove_records']) - 10} 个")
                click.echo()

            if plan["scan_files"]:
                click.echo(f"扫描未入库 PDF ({len(plan['scan_files'])}):")
                for p in plan["scan_files"][:10]:
                    click.echo(f"  + {os.path.basename(p)}")
                if len(plan["scan_files"]) > 10:
                    click.echo(f"  ... 还有 {len(plan['scan_files']) - 10} 个")
                click.echo()

            if plan.get("skipped_unindexed"):
                click.echo(f"保留不动的未入库文件 ({len(plan['skipped_unindexed'])}):")
                for p in plan["skipped_unindexed"][:10]:
                    click.echo(f"  ⏭ 跳过 {os.path.basename(p)}")
                if len(plan["skipped_unindexed"]) > 10:
                    click.echo(f"  ... 还有 {len(plan['skipped_unindexed']) - 10} 个")
                click.echo()

            if plan["ambiguous"]:
                click.echo(f"无法确定重定向目标（歧义） ({len(plan['ambiguous'])}):")
                for miss, cands in plan["ambiguous"][:5]:
                    click.echo(f"  ? {os.path.basename(miss)}")
                    for c in cands:
                        click.echo(f"      → {os.path.basename(c)}")
                if len(plan["ambiguous"]) > 5:
                    click.echo(f"  ... 还有 {len(plan['ambiguous']) - 5} 个")
                click.echo()

            total_fix = (len(plan["redirects"]) + len(plan["remove_records"])
                         + len(plan["scan_files"]))

            if dry_run:
                click.echo(f"(预演模式，共 {total_fix} 项待处理)")
                click.echo("  提示: 可用 --skip-missing <path> / --skip-unindexed <path> 部分跳过")
                return

            if not yes and not click.confirm(f"确认修复以上 {total_fix} 项路径问题?", default=False):
                click.echo("已取消")
                return

            result = apply_path_fixes(db, plan, folder)

            rb = get_rollback(ctx)
            rb.start_batch(f"修复路径一致性: {len(result['removed'])}移除+{len(result['redirected'])}重定向+{len(result['scanned'])}扫描")
            for op_type, details in result["operations_log"]:
                if op_type == "remove_record":
                    rb.record_remove_record(details["file_path"], details["old_metadata"])
                elif op_type == "redirect_path":
                    rb.record_redirect_path(
                        details["old_path"], details["new_path"],
                        details["old_metadata"], details.get("reason")
                    )
                elif op_type == "scan_record":
                    rb.record_scan_record(details["file_path"])
            rb.end_batch()

            save_db(ctx, db)
            click.echo(f"修复完成: 移除 {len(result['removed'])} / 重定向 {len(result['redirected'])} / 扫描 {len(result['scanned'])}")
            click.echo("操作已记录（可使用 rollback 回滚）")
            if result["errors"]:
                click.echo()
                click.echo(f"错误 ({len(result['errors'])}):")
                for e in result["errors"]:
                    click.echo(f"  ✗ {e}")

            # 修复后再次校验
            if recheck:
                click.echo()
                click.echo("=== 修复后再次校验 ===")
                missing_after, unindexed_after = check_path_consistency(db, folder, recursive)
                after_missing = set(_norm(p) for p in missing_after)
                after_unindexed = set(_norm(p) for p in unindexed_after)

                handled_missing = before_missing - after_missing
                remain_missing = before_missing & after_missing
                handled_unindexed = before_unindexed - after_unindexed
                remain_unindexed = before_unindexed & after_unindexed

                click.echo(f"失效记录: 已处理 {len(handled_missing)} / 仍保留 {len(remain_missing)}")
                if remain_missing:
                    click.echo("  仍保留的:")
                    for p in list(remain_missing)[:5]:
                        click.echo(f"    ✗ {os.path.basename(p)}")

                click.echo(f"未入库文件: 已处理 {len(handled_unindexed)} / 仍保留 {len(remain_unindexed)}")
                if remain_unindexed:
                    click.echo("  仍保留的:")
                    for p in list(remain_unindexed)[:5]:
                        click.echo(f"    ? {os.path.basename(p)}")

                if not remain_missing and not remain_unindexed:
                    click.echo("✓ 数据库与文件系统现在完全一致")
                click.echo()
        return

    if not folder and check_type in ("all", "invalid", "paths"):
        click.echo("提示: 使用 --folder 参数可以检查损坏文件和路径一致性")
        click.echo()
        click.echo("提示: 使用 --folder --fix 可以自动修复路径一致性")
        click.echo()

    if folder and not fix_paths:
        missing_files, unindexed_files = check_path_consistency(db, folder, recursive)
        if missing_files or unindexed_files:
            click.echo("--- 一键修复建议 ---")
            click.echo(f"  papertool check --folder {folder} --fix --dry-run  # 预演修复")
            click.echo(f"  papertool check --folder {folder} --fix -y         # 实际修复")
            click.echo(f"  papertool check --folder {folder} --fix -y --skip-missing <path1> --skip-unindexed <path2>  # 部分跳过")
            click.echo()


@cli.command()
@click.option("--steps", type=int, default=None, help="回滚最近 N 个单操作（不推荐，建议用默认的整批回滚）")
@click.option("--batch-id", help="回滚指定的批次 ID（从 rollback --list 获取）")
@click.option("--list", "list_ops", is_flag=True, help="列出最近的操作批次")
@click.option("--all", "rollback_all", is_flag=True, help="回滚所有操作记录")
@click.option("--yes", "-y", is_flag=True, help="跳过确认直接回滚")
@click.pass_context
def rollback(ctx, steps, batch_id, list_ops, rollback_all, yes):
    """回滚最近一次整理操作（默认按整批回滚）

    - 不带参数：回滚最近一整批操作（如 rename --all 的所有文件一起回滚）
    - --list：查看历史批次，显示哪些操作属于同一批
    - --batch-id <id>：回滚指定批次
    - --steps N：回滚最近 N 个单操作
    """
    rb = get_rollback(ctx)

    if list_ops:
        batches = rb.get_batches(20)
        if not batches:
            click.echo("暂无操作记录")
            return
        click.echo("最近操作批次 (新→旧):")
        for i, batch in enumerate(batches, 1):
            bid = batch["batch_id"] or "(单条)"
            desc = batch.get("description") or ""
            ts = batch["timestamp"]
            ops = batch["operations"]
            count = len(ops)

            summary = RollbackManager.summarize_batch(ops)

            click.echo(f"  {i}. [{ts}] batch={bid}")
            if desc:
                click.echo(f"     描述: {desc}")
            click.echo(f"     摘要: {summary}")
            click.echo(f"     操作数: {count}")

            shown = 0
            for op in ops:
                if shown >= 5:
                    break
                if op.summary:
                    click.echo(f"       · {op.summary}")
                else:
                    d = op.details
                    if op.op_type == "rename":
                        click.echo(f"       · rename: {os.path.basename(d.get('old_path',''))} → {os.path.basename(d.get('new_path',''))}")
                    elif op.op_type == "move":
                        click.echo(f"       · move: {os.path.basename(d.get('source',''))} → {os.path.basename(d.get('destination',''))}")
                    elif op.op_type == "metadata_update":
                        click.echo(f"       · meta: {os.path.basename(d.get('file_path',''))}")
                    elif op.op_type == "remove_record":
                        click.echo(f"       · remove: {os.path.basename(d.get('file_path',''))}")
                    elif op.op_type == "redirect_path":
                        click.echo(f"       · redirect: {os.path.basename(d.get('old_path',''))} → {os.path.basename(d.get('new_path',''))}")
                    elif op.op_type == "scan_record":
                        click.echo(f"       · scan: {os.path.basename(d.get('file_path',''))}")
                    else:
                        click.echo(f"       · {op.op_type}")
                shown += 1
            if len(ops) > shown:
                click.echo(f"       · ... 还有 {len(ops) - shown} 个")
            click.echo()
        return

    db = load_db(ctx)

    if batch_id:
        batch_ops = rb.log.get_ops_by_batch(batch_id)
        if not batch_ops:
            click.echo(f"未找到批次 {batch_id}")
            return
        if not yes and not click.confirm(f"确认回滚批次 {batch_id} 共 {len(batch_ops)} 个操作?", default=False):
            click.echo("已取消")
            return
        click.echo(f"准备回滚批次 {batch_id}，共 {len(batch_ops)} 个操作...")
        ops_to_rollback = list(reversed(batch_ops))
        is_batch = True
        rollback_bid = batch_id

    elif rollback_all:
        all_ops = rb.log.operations
        if not all_ops:
            click.echo("没有可回滚的操作")
            return
        if not yes and not click.confirm(f"确认回滚全部 {len(all_ops)} 个操作?", default=False):
            click.echo("已取消")
            return
        click.echo(f"准备回滚全部 {len(all_ops)} 个操作...")
        ops_to_rollback = list(reversed(all_ops))
        is_batch = False
        rollback_bid = None

    elif steps is not None:
        if steps < 1:
            click.echo("steps 必须大于 0")
            return
        all_ops = rb.log.operations
        if not all_ops:
            click.echo("没有可回滚的操作")
            return
        n = min(steps, len(all_ops))
        if not yes and not click.confirm(f"确认回滚最近 {n} 个操作?", default=False):
            click.echo("已取消")
            return
        click.echo(f"准备回滚最近 {n} 步操作...")
        ops_to_rollback = list(reversed(all_ops))[:n]
        is_batch = False
        rollback_bid = None

    else:
        batch_ops = rb.log.get_last_batch_ops()
        if not batch_ops:
            click.echo("没有可回滚的操作")
            return
        bid = batch_ops[0].batch_id
        desc = batch_ops[0].description or ""
        count = len(batch_ops)
        batch_summary = RollbackManager.summarize_batch(batch_ops)
        if not yes and not click.confirm(f"确认回滚最近 1 批操作 ({desc or bid or '单条'}, 共 {count} 个操作)?", default=False):
            click.echo("已取消")
            return
        click.echo(f"准备回滚最近 1 批操作...")
        if desc:
            click.echo(f"批次描述: {desc}")
        click.echo(f"操作摘要: {batch_summary}")
        click.echo(f"操作数量: {count}")
        click.echo()
        ops_to_rollback = list(reversed(batch_ops))
        is_batch = True
        rollback_bid = bid

    success = []
    failed = []

    for op in ops_to_rollback:
        try:
            if op.op_type == "rename":
                old_path = op.details["old_path"]
                new_path = op.details["new_path"]
                paper = db.get_paper(new_path)
                if paper is None:
                    paper = db.get_paper(old_path)
                current_path = paper.file_path if paper else None

                if current_path == new_path and os.path.exists(new_path):
                    os.makedirs(os.path.dirname(old_path), exist_ok=True)
                    os.rename(new_path, old_path)
                    if paper:
                        db.remove_paper(new_path)
                        paper.file_path = old_path
                        from .utils import now_str
                        paper.modified_at = now_str()
                        db.add_paper(paper)
                    success.append(f"回滚重命名: {os.path.basename(new_path)} → {os.path.basename(old_path)}")
                elif current_path == old_path or (paper is None and os.path.exists(old_path)):
                    success.append(f"已在正确位置: {os.path.basename(old_path)}")
                else:
                    failed.append(f"重命名回滚异常 (old={old_path}, new={new_path}, current={current_path})")

            elif op.op_type == "move":
                src = op.details["source"]
                dst = op.details["destination"]
                paper = db.get_paper(dst)
                if paper is None:
                    paper = db.get_paper(src)
                current_path = paper.file_path if paper else None

                if current_path == dst and os.path.exists(dst):
                    os.makedirs(os.path.dirname(src), exist_ok=True)
                    os.rename(dst, src)
                    if paper:
                        db.remove_paper(dst)
                        paper.file_path = src
                        from .utils import now_str
                        paper.modified_at = now_str()
                        db.add_paper(paper)
                    success.append(f"回滚移动: {os.path.basename(dst)} → {os.path.basename(src)}")
                elif current_path == src or (paper is None and os.path.exists(src)):
                    success.append(f"已在正确位置: {os.path.basename(src)}")
                else:
                    failed.append(f"移动回滚异常 (src={src}, dst={dst}, current={current_path})")

            elif op.op_type == "metadata_update":
                file_path = op.details["file_path"]
                old_meta = op.details.get("old_metadata", {})
                paper = db.get_paper(file_path)
                if paper:
                    for field in ("title", "doi", "journal", "topic", "read_status", "notes", "year"):
                        if field in old_meta:
                            setattr(paper, field, old_meta[field])
                    for field in ("authors", "keywords", "tags"):
                        if field in old_meta and isinstance(old_meta[field], list):
                            setattr(paper, field, list(old_meta[field]))
                    from .utils import now_str
                    paper.modified_at = now_str()
                    db.add_paper(paper)
                    success.append(f"回滚元数据: {os.path.basename(file_path)}")
                elif os.path.exists(file_path):
                    new_paper = PaperMetadata(file_path=file_path)
                    for field in ("title", "doi", "journal", "topic", "read_status", "notes", "year"):
                        if field in old_meta:
                            setattr(new_paper, field, old_meta[field])
                    for field in ("authors", "keywords", "tags"):
                        if field in old_meta and isinstance(old_meta[field], list):
                            setattr(new_paper, field, list(old_meta[field]))
                    db.add_paper(new_paper)
                    success.append(f"回滚元数据 (已重新载入): {os.path.basename(file_path)}")
                else:
                    failed.append(f"文件不存在，无法回滚元数据: {file_path}")

            elif op.op_type == "remove_record":
                file_path = op.details["file_path"]
                old_meta = op.details.get("old_metadata", {})
                if db.get_paper(file_path):
                    success.append(f"记录已存在: {os.path.basename(file_path)}")
                else:
                    # 即使原 PDF 暂时不在，也要恢复记录（后续可再用 check 重新指向）
                    new_paper = PaperMetadata(file_path=file_path)
                    for field in ("title", "doi", "journal", "topic", "read_status", "notes", "year",
                                  "file_hash", "file_size", "added_at"):
                        if field in old_meta:
                            setattr(new_paper, field, old_meta[field])
                    for field in ("authors", "keywords", "tags"):
                        if field in old_meta and isinstance(old_meta[field], list):
                            setattr(new_paper, field, list(old_meta[field]))
                    from .utils import now_str
                    new_paper.modified_at = now_str()
                    db.add_paper(new_paper)
                    if os.path.exists(file_path):
                        success.append(f"恢复已移除记录: {os.path.basename(file_path)}")
                    else:
                        success.append(f"恢复已移除记录 (PDF暂不在，记录已恢复): {os.path.basename(file_path)}")

            elif op.op_type == "redirect_path":
                old_path = op.details["old_path"]
                new_path = op.details["new_path"]
                old_meta = op.details.get("old_metadata", {})
                paper = db.get_paper(new_path)
                current_path = paper.file_path if paper else None
                if current_path == new_path:
                    if not db.get_paper(old_path):
                        db.remove_paper(new_path)
                        paper.file_path = old_path
                        from .utils import now_str
                        paper.modified_at = now_str()
                        db.add_paper(paper)
                        success.append(f"撤销重定向: {os.path.basename(new_path)} → {os.path.basename(old_path)}")
                    else:
                        success.append(f"旧路径已存在记录，保持原状: {os.path.basename(old_path)}")
                elif current_path == old_path:
                    success.append(f"已在原位置: {os.path.basename(old_path)}")
                else:
                    failed.append(f"撤销重定向失败，当前路径不匹配: current={current_path}")

            elif op.op_type == "scan_record":
                file_path = op.details["file_path"]
                paper = db.get_paper(file_path)
                if paper:
                    db.remove_paper(file_path)
                    success.append(f"移除扫描入库记录: {os.path.basename(file_path)} (注意: PDF 文件仍保留)")
                else:
                    success.append(f"记录已不存在: {os.path.basename(file_path)}")

            else:
                failed.append(f"未知操作类型，无法回滚: {op.op_type}")

        except Exception as e:
            failed.append(f"回滚失败 ({op.op_type}): {str(e)}")

    all_success = len(failed) == 0

    if all_success:
        if is_batch and rollback_bid:
            rb.log.remove_batch(rollback_bid)
        elif is_batch and not rollback_bid:
            n = len(ops_to_rollback)
            if n <= len(rb.log.operations):
                rb.log.operations = rb.log.operations[:-n]
                rb.log._save()
        else:
            n = len(ops_to_rollback)
            if n <= len(rb.log.operations):
                rb.log.operations = rb.log.operations[:-n]
                rb.log._save()
    else:
        # 存在失败项，保留操作记录在 rollback --list 中方便继续处理或重试
        click.echo(f"[INFO] 存在 {len(failed)} 个失败项，操作记录未从 rollback 日志移除，可再次 rollback 继续处理")

    save_db(ctx, db)

    if success:
        click.echo("回滚成功:")
        for msg in success:
            click.echo(f"  ✓ {msg}")
        click.echo()

    if failed:
        click.echo("回滚失败 (操作记录仍保留在日志中，可再次 rollback 重试):")
        for msg in failed:
            click.echo(f"  ✗ {msg}")
        click.echo()
        click.echo("提示: 用 rollback --list 查看仍保留的操作记录")

    click.echo("回滚完成，数据库已同步更新")
    click.echo("提示: 可用 list、export、check 命令验证结果一致性")


@cli.command("list")
@click.option("--topic", help="按课题筛选")
@click.option("--tag", help="按标签筛选")
@click.option("--status", type=click.Choice(["unread", "reading", "read", "skimmed"]), help="按阅读状态筛选")
@click.option("--author", help="按作者筛选")
@click.option("--title", help="按标题关键词筛选")
@click.pass_context
def list_cmd(ctx, topic, tag, status, author, title):
    """列出数据库中的论文"""
    db = load_db(ctx)
    papers = _find_papers(
        db, title=title, author=author,
        tags=[tag] if tag else None,
        topic=topic, read_status=status,
    )

    if not papers:
        click.echo("没有找到符合条件的论文")
        return

    click.echo(f"共找到 {len(papers)} 篇论文:")
    click.echo()
    for i, paper in enumerate(papers, 1):
        _print_paper_short(paper, i)


def _print_paper_info(paper):
    click.echo("论文信息:")
    click.echo(f"  文件: {paper.file_path}")
    click.echo(f"  标题: {paper.title or '未知'}")
    click.echo(f"  作者: {', '.join(paper.authors) if paper.authors else '未知'}")
    click.echo(f"  年份: {paper.year or '未知'}")
    click.echo(f"  期刊: {paper.journal or '未知'}")
    click.echo(f"  DOI: {paper.doi or '未知'}")
    click.echo(f"  关键词: {', '.join(paper.keywords) if paper.keywords else '无'}")
    click.echo(f"  标签: {', '.join(paper.tags) if paper.tags else '无'}")
    click.echo(f"  课题: {paper.topic or '未分类'}")
    click.echo(f"  阅读状态: {paper.read_status}")
    if paper.notes:
        click.echo(f"  备注: {paper.notes}")
    click.echo(f"  文件大小: {format_file_size(paper.file_size)}")


def _print_paper_short(paper, index=None):
    prefix = f"{index}. " if index else "  "
    title = paper.title or "未知标题"
    year = paper.year or "----"
    status = paper.read_status
    tags = f" [{', '.join(paper.tags[:3])}]" if paper.tags else ""
    click.echo(f"{prefix}[{year}] {title}{tags} ({status})")
    if paper.authors:
        authors = ", ".join(paper.authors[:2])
        if len(paper.authors) > 2:
            authors += " 等"
        click.echo(f"     作者: {authors}")
    if paper.topic:
        click.echo(f"     课题: {paper.topic}")
    click.echo(f"     文件: {paper.file_path}")
    click.echo()


def main():
    cli()


if __name__ == "__main__":
    main()
