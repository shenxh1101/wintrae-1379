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


def export_csv(papers: List[PaperMetadata], output_path: str) -> int:
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


def export_reading_list(papers: List[PaperMetadata], output_path: str,
                        group_by: List[str] = None) -> int:
    """
    导出阅读书单，支持多层级树状分组。

    同一个上层分组只出现一次，下层按嵌套结构继续分组。
    分组和论文顺序都稳定排序。

    Args:
        papers: 论文列表
        output_path: 输出文件路径
        group_by: 分组字段列表，如 ["topic", "year", "read_status"]
                  支持: topic, read_status, year
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

        def _count_all(node: Node) -> int:
            c = len(node.papers)
            for ch in node.children.values():
                c += _count_all(ch)
            return c

        def write_node(node: Node):
            nonlocal total

            if node.level >= 0:
                count = _count_all(node)
                f.write(f"{'#' * (node.level + 2)} {node.key} ({count}篇)\n\n")

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
