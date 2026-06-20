import csv
import os
from typing import List

from .models import PaperMetadata


def _sort_key(paper: PaperMetadata):
    """稳定排序键：课题→年份→标题→路径，保证 CSV 和 Markdown 顺序一致。"""
    return (
        paper.topic or "ZZZZ",
        -(paper.year or 0),
        (paper.title or "").lower(),
        paper.file_path or "",
    )


def export_bibtex(papers: List[PaperMetadata], output_path: str) -> int:
    count = 0
    sorted_papers = sorted(papers, key=_sort_key)
    with open(output_path, "w", encoding="utf-8") as f:
        for index, paper in enumerate(sorted_papers):
            entry = _paper_to_bibtex(paper, index)
            if entry:
                f.write(entry + "\n\n")
                count += 1
    return count


def _paper_to_bibtex(paper: PaperMetadata, index: int) -> str:
    key = paper.doi or f"paper_{index}"
    key = key.replace("/", "_").replace(".", "_")

    entry_type = "article" if paper.journal else "misc"

    lines = [f"@{entry_type}{{{key},"]

    if paper.title:
        lines.append(f"  title = {{{paper.title}}},")

    if paper.authors:
        authors_str = " and ".join(paper.authors)
        lines.append(f"  author = {{{authors_str}}},")

    if paper.year:
        lines.append(f"  year = {{{paper.year}}},")

    if paper.journal:
        lines.append(f"  journal = {{{paper.journal}}},")

    if paper.doi:
        lines.append(f"  doi = {{{paper.doi}}},")

    if paper.keywords:
        lines.append(f"  keywords = {{{', '.join(paper.keywords)}}},")

    if paper.file_path:
        lines.append(f"  file = {{{paper.file_path}}},")

    if len(lines) > 1:
        lines[-1] = lines[-1].rstrip(",")
        lines.append("}")
        return "\n".join(lines)

    return ""


def export_csv(papers: List[PaperMetadata], output_path: str,
               include_summary: bool = False) -> int:
    fieldnames = [
        "title",
        "authors",
        "year",
        "doi",
        "journal",
        "keywords",
        "tags",
        "read_status",
        "topic",
        "file_path",
        "file_size",
    ]

    sorted_papers = sorted(papers, key=_sort_key)
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)

        if include_summary:
            stats = _build_summary_stats(sorted_papers)
            writer.writerow({"title": f"=== 汇总: 共{stats['total']}篇 / 待读{stats['unread']}篇 / 已读{stats['read']}篇 / 阅读中{stats['reading']}篇 ==="})
            writer.writerow({})
            writer.writerow({"title": "--- 按课题 ---", "topic": "篇数", "read_status": "待读"})
            for t, d in sorted(stats["by_topic"].items()):
                writer.writerow({"title": t, "topic": str(d["total"]), "read_status": str(d["unread"])})
            writer.writerow({})
            writer.writerow({"title": "--- 按年份 ---", "year": "篇数", "read_status": "待读"})
            for y, d in sorted(stats["by_year"].items(), reverse=True):
                writer.writerow({"title": str(y), "year": str(d["total"]), "read_status": str(d["unread"])})
            writer.writerow({})
            writer.writerow({"title": "--- 按阅读状态 ---", "read_status": "篇数"})
            for s, c in sorted(stats["by_status"].items()):
                writer.writerow({"title": s, "read_status": str(c)})
            writer.writerow({})
            writer.writerow(dict(zip(fieldnames, fieldnames)))

        writer.writeheader()
        for paper in sorted_papers:
            row = {
                "title": paper.title or "",
                "authors": "; ".join(paper.authors) if paper.authors else "",
                "year": paper.year or "",
                "doi": paper.doi or "",
                "journal": paper.journal or "",
                "keywords": "; ".join(paper.keywords) if paper.keywords else "",
                "tags": "; ".join(paper.tags) if paper.tags else "",
                "read_status": paper.read_status or "",
                "topic": paper.topic or "",
                "file_path": paper.file_path or "",
                "file_size": paper.file_size or 0,
            }
            writer.writerow(row)

    return len(sorted_papers)


def _build_summary_stats(papers: List[PaperMetadata]) -> dict:
    """构建汇总统计：总数/按课题/按年份/按状态，含待读数量。"""
    total = len(papers)
    by_topic = {}
    by_year = {}
    by_status = {}

    unread = 0
    read = 0
    reading = 0

    for p in papers:
        s = (p.read_status or "unread").lower()
        if s in {"unread", "todo", "未读", ""}:
            unread += 1
        elif s in {"read", "done", "finished", "已读"}:
            read += 1
        elif s in {"reading", "doing", "wip", "阅读中"}:
            reading += 1

        t = p.topic or "未分类"
        if t not in by_topic:
            by_topic[t] = {"total": 0, "unread": 0, "read": 0, "reading": 0}
        by_topic[t]["total"] += 1
        if s in {"unread", "todo", "未读", ""}:
            by_topic[t]["unread"] += 1
        elif s in {"read", "done", "finished", "已读"}:
            by_topic[t]["read"] += 1
        else:
            by_topic[t]["reading"] += 1

        y = str(p.year) if p.year else "未知年份"
        if y not in by_year:
            by_year[y] = {"total": 0, "unread": 0, "read": 0, "reading": 0}
        by_year[y]["total"] += 1
        if s in {"unread", "todo", "未读", ""}:
            by_year[y]["unread"] += 1
        elif s in {"read", "done", "finished", "已读"}:
            by_year[y]["read"] += 1
        else:
            by_year[y]["reading"] += 1

        st = p.read_status or "unread"
        by_status[st] = by_status.get(st, 0) + 1

    return {
        "total": total,
        "unread": unread,
        "read": read,
        "reading": reading,
        "by_topic": by_topic,
        "by_year": by_year,
        "by_status": by_status,
    }


def export_reading_list(papers: List[PaperMetadata], output_path: str,
                        group_by: List[str] = None,
                        include_summary: bool = False) -> int:
    """
    导出阅读书单，支持多层级树状分组和汇总模式。

    同一个上层分组只出现一次，下层按嵌套结构继续分组。
    分组和论文顺序都稳定排序。

    Args:
        papers: 论文列表
        output_path: 输出文件路径
        group_by: 分组字段列表，如 ["topic", "year", "read_status"]
                  支持: topic, read_status, year
        include_summary: 是否在开头包含汇总统计（课题/年份/状态，含待读数量）
    """
    if group_by is None:
        group_by = ["topic"]

    def _field_sort_val(field: str, paper: PaperMetadata):
        if field == "topic":
            return paper.topic or "未分类"
        elif field == "read_status":
            return paper.read_status or "unknown"
        elif field == "year":
            return str(paper.year) if paper.year else "未知年份"
        return "全部"

    sorted_papers = sorted(papers, key=_sort_key)

    class Node:
        __slots__ = ("key", "level", "papers", "children")
        def __init__(self, key, level):
            self.key = key
            self.level = level
            self.papers = []
            self.children = {}

    root = Node(None, -1)

    for paper in sorted_papers:
        node = root
        for depth, field in enumerate(group_by):
            k = _field_sort_val(field, paper)
            if k not in node.children:
                node.children[k] = Node(k, depth)
            node = node.children[k]
        node.papers.append(paper)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("# 阅读书单\n\n")
        total = 0

        if include_summary:
            stats = _build_summary_stats(sorted_papers)
            f.write("## 总体汇总\n\n")
            f.write(f"- 论文总数: **{stats['total']}** 篇\n")
            f.write(f"- 待读: **{stats['unread']}** 篇  |  已读: **{stats['read']}** 篇  |  阅读中: **{stats['reading']}** 篇\n\n")

            if stats["by_topic"]:
                f.write("### 按课题统计\n\n")
                f.write("| 课题 | 总数 | 待读 | 已读 | 阅读中 |\n")
                f.write("|------|------|------|------|--------|\n")
                for t in sorted(stats["by_topic"].keys()):
                    d = stats["by_topic"][t]
                    f.write(f"| {t} | {d['total']} | {d['unread']} | {d['read']} | {d['reading']} |\n")
                f.write("\n")

            if stats["by_year"]:
                f.write("### 按年份统计\n\n")
                f.write("| 年份 | 总数 | 待读 | 已读 | 阅读中 |\n")
                f.write("|------|------|------|------|--------|\n")
                for y in sorted(stats["by_year"].keys(), reverse=True):
                    d = stats["by_year"][y]
                    f.write(f"| {y} | {d['total']} | {d['unread']} | {d['read']} | {d['reading']} |\n")
                f.write("\n")

            if stats["by_status"]:
                f.write("### 按阅读状态统计\n\n")
                f.write("| 状态 | 篇数 |\n")
                f.write("|------|------|\n")
                for s in sorted(stats["by_status"].keys()):
                    f.write(f"| {s} | {stats['by_status'][s]} |\n")
                f.write("\n")

            f.write("---\n\n")

        def _count_all(node: Node) -> tuple:
            """返回 (total, unread, read, reading) 计数。"""
            t = len(node.papers)
            u = r = rd = 0
            for p in node.papers:
                s = (p.read_status or "unread").lower()
                if s in {"unread", "todo", "未读", ""}:
                    u += 1
                elif s in {"read", "done", "finished", "已读"}:
                    r += 1
                else:
                    rd += 1
            for ch in node.children.values():
                ct, cu, cr, crd = _count_all(ch)
                t += ct
                u += cu
                r += cr
                rd += crd
            return t, u, r, rd

        def write_node(node: Node):
            nonlocal total

            if node.level >= 0:
                ct, cu, cr, crd = _count_all(node)
                header = f"{'#' * (node.level + 2)} {node.key} ({ct}篇"
                if cu or cr or crd:
                    parts = []
                    if cu:
                        parts.append(f"待读{cu}")
                    if cr:
                        parts.append(f"已读{cr}")
                    if crd:
                        parts.append(f"阅读中{crd}")
                    if parts:
                        header += ", " + "/".join(parts)
                header += ")\n\n"
                f.write(header)

            if node.papers:
                for i, paper in enumerate(node.papers, 1):
                    total += 1
                    title = paper.title or "未知标题"
                    authors = ", ".join(paper.authors) if paper.authors else "未知作者"
                    year = paper.year or "----"
                    status = paper.read_status or "unread"

                    f.write(f"{i}. **{title}**\n")
                    f.write(f"   - 作者: {authors}\n")
                    f.write(f"   - 年份: {year}\n")
                    if paper.journal:
                        f.write(f"   - 期刊: {paper.journal}\n")
                    if paper.doi:
                        f.write(f"   - DOI: {paper.doi}\n")
                    if paper.tags:
                        f.write(f"   - 标签: {', '.join(paper.tags)}\n")
                    if "topic" not in group_by:
                        f.write(f"   - 课题: {paper.topic or '未分类'}\n")
                    if "read_status" not in group_by:
                        f.write(f"   - 状态: {status}\n")
                    f.write(f"   - 文件: `{paper.file_path}`\n\n")

            for child_key in sorted(node.children.keys()):
                write_node(node.children[child_key])

        write_node(root)

    return total
