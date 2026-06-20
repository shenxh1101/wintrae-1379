"""测试脚本：验证 papertool 的各个功能
"""
import os
import sys
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from papertool.models import PaperMetadata, PaperDatabase
from papertool.utils import generate_filename, sanitize_filename, compute_file_hash
from papertool.exporter import export_bibtex, export_csv, export_reading_list
from papertool.checker import check_duplicates, check_missing_metadata
from papertool.operations import RollbackManager
from papertool.pdf_parser import parse_filename_for_metadata


def test_models():
    print("=== 测试数据模型 ===")
    paper = PaperMetadata(
        file_path="/test/paper.pdf",
        title="Deep Learning for Natural Language Processing",
        authors=["John Smith", "Jane Doe"],
        year=2023,
        doi="10.1234/test",
        journal="Journal of AI",
        tags=["nlp", "deep-learning"],
        read_status="reading",
        topic="自然语言处理",
    )
    
    d = paper.to_dict()
    assert d["title"] == "Deep Learning for Natural Language Processing"
    assert len(d["authors"]) == 2
    assert d["year"] == 2023
    
    paper2 = PaperMetadata.from_dict(d)
    assert paper2.title == paper.title
    assert paper2.authors == paper.authors
    
    print("✓ 数据模型测试通过")
    print()


def test_database():
    print("=== 测试数据库 ===")
    db = PaperDatabase()
    
    p1 = PaperMetadata(file_path="/a.pdf", title="Paper 1", year=2020)
    p2 = PaperMetadata(file_path="/b.pdf", title="Paper 2", year=2021)
    
    db.add_paper(p1)
    db.add_paper(p2)
    
    assert len(db.all_papers()) == 2
    assert db.get_paper("/a.pdf") is not None
    assert db.get_paper("/nonexistent.pdf") is None
    
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        db_path = f.name
    
    try:
        db.save(db_path)
        assert os.path.exists(db_path)
        
        db2 = PaperDatabase.load(db_path)
        assert len(db2.all_papers()) == 2
        assert db2.get_paper("/a.pdf").title == "Paper 1"
        
        db2.remove_paper("/a.pdf")
        assert len(db2.all_papers()) == 1
        
        print("✓ 数据库测试通过")
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)
    print()


def test_utils():
    print("=== 测试工具函数 ===")
    
    filename = generate_filename(
        title="A Very Important Research Paper About Machine Learning",
        authors=["Alice Wang", "Bob Li"],
        year=2024,
    )
    print(f"生成的文件名: {filename}")
    assert "2024" in filename
    assert ".pdf" in filename
    
    dirty = 'File/Name: with? <bad> chars.pdf'
    clean = sanitize_filename(dirty)
    print(f"清理后文件名: {clean}")
    assert "/" not in clean
    assert "?" not in clean
    
    print("✓ 工具函数测试通过")
    print()


def test_filename_parsing():
    print("=== 测试文件名解析 ===")
    
    test_cases = [
        "2023 - Smith et al - Deep Learning Paper.pdf",
        "Deep Learning Survey 2022.pdf",
        "10.1234_journal_paper.pdf",
    ]
    
    for fname in test_cases:
        meta = parse_filename_for_metadata(fname)
        print(f"  {fname}")
        print(f"    标题: {meta.get('title')}")
        print(f"    作者: {meta.get('authors')}")
        print(f"    年份: {meta.get('year')}")
        print(f"    DOI: {meta.get('doi')}")
    
    print("✓ 文件名解析测试通过")
    print()


def test_exporter():
    print("=== 测试导出功能 ===")
    
    papers = [
        PaperMetadata(
            file_path="/paper1.pdf",
            title="Deep Learning Paper",
            authors=["Author One", "Author Two"],
            year=2023,
            journal="AI Journal",
            doi="10.1234/paper1",
            tags=["dl", "nlp"],
            read_status="read",
            topic="深度学习",
        ),
        PaperMetadata(
            file_path="/paper2.pdf",
            title="Another Paper",
            authors=["Single Author"],
            year=2022,
            read_status="unread",
            topic="机器学习",
        ),
    ]
    
    with tempfile.TemporaryDirectory() as tmpdir:
        bib_path = os.path.join(tmpdir, "refs.bib")
        count = export_bibtex(papers, bib_path)
        print(f"BibTeX 导出: {count} 篇")
        assert count == 2
        assert os.path.exists(bib_path)
        with open(bib_path, encoding="utf-8") as f:
            content = f.read()
        assert "Deep Learning Paper" in content
        assert "@article" in content
        
        csv_path = os.path.join(tmpdir, "papers.csv")
        count = export_csv(papers, csv_path)
        print(f"CSV 导出: {count} 篇")
        assert count == 2
        
        md_path = os.path.join(tmpdir, "reading.md")
        count = export_reading_list(papers, md_path, group_by="topic")
        print(f"阅读书单导出: {count} 篇")
        assert "## 深度学习" in open(md_path, encoding="utf-8").read()
    
    print("✓ 导出功能测试通过")
    print()


def test_checker():
    print("=== 测试检查功能 ===")
    
    db = PaperDatabase()
    
    p1 = PaperMetadata(file_path="/a.pdf", title="Paper A", year=2020, file_hash="abc123", authors=["Author 1"])
    p2 = PaperMetadata(file_path="/b.pdf", title="Paper B", year=2021, file_hash="def456", authors=["Author 2"])
    p3 = PaperMetadata(file_path="/c.pdf", title="Paper A", year=2020, file_hash="abc123", authors=["Author 3"])
    
    db.add_paper(p1)
    db.add_paper(p2)
    db.add_paper(p3)
    
    dupes = check_duplicates(db, by="hash")
    print(f"重复文献组数: {len(dupes)}")
    assert len(dupes) == 1
    assert len(dupes[0]) == 2
    
    missing = check_missing_metadata(db)
    print(f"缺少元数据的论文数: {len(missing)}")
    
    p4 = PaperMetadata(file_path="/d.pdf")
    db.add_paper(p4)
    
    missing = check_missing_metadata(db)
    print(f"添加缺少信息的论文后: {len(missing)}")
    assert len(missing) >= 1
    
    print("✓ 检查功能测试通过")
    print()


def test_rollback():
    print("=== 测试回滚功能 ===")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        log_dir = os.path.join(tmpdir, "logs")
        rb = RollbackManager(log_dir)
        
        rb.record_rename("/old/a.pdf", "/new/a.pdf")
        rb.record_metadata_update("/some/file.pdf", {"title": "old"}, {"title": "new"})
        
        history = rb.get_history(10)
        print(f"操作记录数: {len(history)}")
        assert len(history) == 2
        
        results = rb.rollback_last(1)
        print(f"回滚成功数: {len(results['success'])}")
        
        history = rb.get_history(10)
        print(f"回滚后记录数: {len(history)}")
        assert len(history) == 1
    
    print("✓ 回滚功能测试通过")
    print()


def main():
    print("=" * 60)
    print("Paper Tool 功能测试")
    print("=" * 60)
    print()
    
    try:
        test_models()
        test_database()
        test_utils()
        test_filename_parsing()
        test_exporter()
        test_checker()
        test_rollback()
        
        print("=" * 60)
        print("所有测试通过！✓")
        print("=" * 60)
        return 0
    except Exception as e:
        print(f"\n测试失败: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
