import csv
import os
from typing import List

from .models import PaperMetadata


def export_bibtex(papers: List[PaperMetadata], output_path: str) -> int:
    count = 0
    with open(output_path, "w", encoding="utf-8") as f:
        for paper in papers:
            entry = _paper_to_bibtex(paper, count)
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

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for paper in papers:
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

    return len(papers)


def export_reading_list(papers: List[PaperMetadata], output_path: str, group_by: str = "topic") -> int:
    grouped = {}
    for paper in papers:
        if group_by == "topic":
            key = paper.topic or "未分类"
        elif group_by == "read_status":
            key = paper.read_status or "unknown"
        elif group_by == "year":
            key = str(paper.year) if paper.year else "未知年份"
        else:
            key = "全部文献"
        grouped.setdefault(key, []).append(paper)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("# 阅读书单\n\n")
        total = 0

        for group_key in sorted(grouped.keys()):
            group_papers = grouped[group_key]
            f.write(f"## {group_key} ({len(group_papers)}篇)\n\n")

            for i, paper in enumerate(group_papers, 1):
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
                f.write(f"   - 状态: {status}\n")
                f.write(f"   - 文件: `{paper.file_path}`\n\n")

    return total
