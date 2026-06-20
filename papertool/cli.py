import os
import sys

import click

from .__init__ import __version__
from .models import PaperDatabase
from .manager import (
    scan_folder,
    rename_papers,
    move_by_topic,
    update_paper_metadata,
    add_tags,
    remove_tags,
    set_read_status,
    find_papers,
)
from .exporter import export_bibtex, export_csv, export_reading_list
from .checker import run_full_check, check_duplicates, check_missing_metadata
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

    new_db, new_count = scan_folder(
        folder,
        recursive=recursive,
        extract_meta=extract_meta,
        db=db,
    )

    click.echo(f"扫描完成，共发现 {new_count} 篇新论文")
    click.echo(f"数据库现有 {len(new_db.all_papers())} 篇 (之前有 {initial_count} 篇")
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
@click.pass_context
def rename(ctx, folder, all_papers, dry_run, conflict):
    """按标题、作者、年份规范重命名 PDF 文件"""
    db = load_db(ctx)

    if not db.all_papers():
        click.echo("数据库为空，请先使用 scan 命令扫描论文")
        return

    target_paths = None
    if folder:
        target_paths = [
            p for p in db.papers.keys() if p.startswith(os.path.abspath(folder))]
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

    renamed, conflicts = rename_papers(
        db,
        paper_paths=target_paths,
        dry_run=dry_run,
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

    if not dry_run and renamed:
        rb = get_rollback(ctx)
        for old, new in renamed:
            rb.record_rename(old, new)
        save_db(ctx, db)
        click.echo("文件已重命名，操作已记录（可使用 rollback 回滚")
    elif dry_run:
        click.echo("(预演模式，未实际修改)")


@cli.command()
@click.argument("file-path", type=click.Path(exists=True))
@click.option("--add", "add_tags_list", multiple=True, help="添加标签，可多次指定")
@click.option("--remove", "remove_tags_list", multiple=True, help="移除标签，可多次指定")
@click.option("--topic", help="设置课题分组")
@click.option("--status", type=click.Choice(["unread", "reading", "read", "skimmed"]), help="设置阅读状态")
@click.option("--doi", help="设置 DOI")
@click.option("--journal", help="设置期刊名")
@click.option("--title", help="设置标题")
@click.option("--year", type=int, help="设置年份")
@click.option("--author", multiple=True, help="添加作者，可多次指定")
@click.option("--keyword", multiple=True, help="添加关键词，可多次指定")
@click.pass_context
def tag(ctx, file_path, add_tags_list, remove_tags_list, topic, status, doi, journal, title, year, author, keyword):
    """为论文添加/移除标签，补充元数据和阅读状态"""
    db = load_db(ctx)
    abs_path = os.path.abspath(os.path.normpath(file_path))

    import sys
    print("DEBUG add_tags_list:", repr(add_tags_list), file=sys.stderr)
    print("DEBUG type(add_tags_list):", type(add_tags_list), file=sys.stderr)
    print("DEBUG add_tags:", add_tags, file=sys.stderr)
    print("DEBUG add_tags.__module__:", getattr(add_tags, '__module__', '?'), file=sys.stderr)
    print("DEBUG globals()['add_tags']:", globals().get('add_tags', 'NOT FOUND'), file=sys.stderr)

    paper = db.get_paper(abs_path)
    if not paper:
        click.echo(f"未找到论文: {file_path}")
        click.echo("请先使用 scan 命令扫描该文件")
        return

    old_meta = paper.to_dict()

    if add_tags_list:
        import sys
        print("DEBUG before add_tags call", file=sys.stderr)
        add_tags(db, abs_path, list(add_tags_list))
        print("DEBUG after add_tags call", file=sys.stderr)
        click.echo(f"添加标签: {', '.join(add_tags_list)}")

    if remove_tags_list:
        remove_tags(db, abs_path, list(remove_tags_list))
        click.echo(f"移除标签: {', '.join(remove_tags_list)}")

    updates = {}
    if topic:
        updates["topic"] = topic
    if status:
        updates["read_status"] = status
    if doi:
        updates["doi"] = doi
    if journal:
        updates["journal"] = journal
    if title:
        updates["title"] = title
    if year:
        updates["year"] = year
    if author:
        updates["authors"] = list(author)
    if keyword:
        updates["keywords"] = list(keyword)

    if updates:
        update_paper_metadata(db, abs_path, **updates)
        for k, v in updates.items():
            click.echo(f"设置 {k}: {v}")

    paper = db.get_paper(abs_path)
    click.echo()
    _print_paper_info(paper)

    rb = get_rollback(ctx)
    rb.record_metadata_update(abs_path, old_meta, paper.to_dict())

    save_db(ctx, db)


@cli.command()
@click.argument("output", type=click.Path())
@click.option("--format", "fmt", type=click.Choice(["bibtex", "csv", "reading"]), default="bibtex", help="导出格式")
@click.option("--topic", help="按课题筛选")
@click.option("--tag", help="按标签筛选")
@click.option("--status", type=click.Choice(["unread", "reading", "read", "skimmed"]), help="按阅读状态筛选")
@click.option("--group-by", type=click.Choice(["topic", "read_status", "year"]), default="topic", help="阅读书单分组方式")
@click.pass_context
def export(ctx, output, fmt, topic, tag, status, group_by):
    """导出文献信息为 BibTeX、CSV 或阅读书单"""
    db = load_db(ctx)

    papers = db.all_papers()

    if topic:
        papers = [p for p in papers if p.topic == topic]
    if tag:
        papers = [p for p in papers if tag in p.tags]
    if status:
        papers = [p for p in papers if p.read_status == status]

    if not papers:
        click.echo("没有符合条件的论文")
        return

    click.echo(f"准备导出 {len(papers)} 篇论文...")

    count = 0
    if fmt == "bibtex":
        count = export_bibtex(papers, output)
        click.echo(f"BibTeX 已导出到: {output}")
    elif fmt == "csv":
        count = export_csv(papers, output)
        click.echo(f"CSV 已导出到: {output}")
    elif fmt == "reading":
        count = export_reading_list(papers, output, group_by)
        click.echo(f"阅读书单已导出到: {output} (按 {group_by} 分组)")

    click.echo(f"共 {count} 条记录")


@cli.command()
@click.option("--folder", type=click.Path(exists=True, file_okay=False), help="指定文件夹检查")
@click.option("--check-type", type=click.Choice(["all", "duplicates", "missing", "invalid"]), default="all", help="检查类型")
@click.option("--recursive/--no-recursive", default=True, help="是否递归检查")
@click.pass_context
def check(ctx, folder, check_type, recursive):
    """检查重复文献、缺失元数据和打不开的文件"""
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
                    title = paper.title or "未知标题"
                    click.echo(f"    - {os.path.basename(paper.file_path)}: {title}")
            if len(dupes) > 5:
                click.echo(f"  ... 还有 {len(dupes) - 5} 组")
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
        else:
            click.echo("所有论文元数据完整 ✓")
        click.echo()

    if check_type in ("all", "invalid") and folder:
        click.echo("=== 损坏文件检查 ===")
        from .checker import check_invalid_files
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

    if not folder and check_type in ("all", "invalid"):
        click.echo("提示: 使用 --folder 参数可以检查损坏文件")
        click.echo()


@cli.command()
@click.option("--steps", type=int, default=1, help="回滚最近几步操作")
@click.option("--list", "list_ops", is_flag=True, help="列出最近的操作记录")
@click.pass_context
def rollback(ctx, steps, list_ops):
    """回滚最近一次整理操作"""
    rb = get_rollback(ctx)

    if list_ops:
        history = rb.get_history(20)
        if not history:
            click.echo("暂无操作记录")
            return
        click.echo("最近操作记录:")
        for i, op in enumerate(reversed(history), 1):
            click.echo(f"  {i}. [{op['timestamp']}] {op['op_type']}")
            details = op.get('details', {})
            if 'old_path' in details:
                click.echo(f"     {os.path.basename(details['old_path'])} -> {os.path.basename(details['new_path'])}")
            elif 'file_path' in details:
                click.echo(f"     {details['file_path']}")
        return

    if steps < 1:
        click.echo("steps 必须大于 0")
        return

    click.echo(f"准备回滚最近 {steps} 步操作...")
    click.echo()

    results = rb.rollback_last(steps)

    if results["success"]:
        click.echo("回滚成功:")
        for msg in results["success"]:
            click.echo(f"  ✓ {msg}")
        click.echo()

    if results["failed"]:
        click.echo("回滚失败:")
        for msg in results["failed"]:
            click.echo(f"  ✗ {msg}")
        click.echo()

    db = load_db(ctx)
    papers_to_remove = []
    for paper in db.all_papers():
        if not os.path.exists(paper.file_path):
            papers_to_remove.append(paper.file_path)

    for path in papers_to_remove:
        db.remove_paper(path)

    if papers_to_remove:
        save_db(ctx, db)
        click.echo(f"已从数据库移除 {len(papers_to_remove)} 条不存在的记录")

    click.echo("回滚完成")


@cli.command()
@click.option("--topic", help="按课题筛选")
@click.option("--tag", help="按标签筛选")
@click.option("--status", type=click.Choice(["unread", "reading", "read", "skimmed"]), help="按阅读状态筛选")
@click.option("--author", help="按作者筛选")
@click.option("--title", help="按标题关键词筛选")
@click.pass_context
def list(ctx, topic, tag, status, author, title):
    """列出数据库中的论文"""
    db = load_db(ctx)
    papers = find_papers(db, title=title, author=author, tags=[tag] if tag else None,
                         topic=topic, read_status=status)

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
    click.echo()


def main():
    cli()


if __name__ == "__main__":
    main()
