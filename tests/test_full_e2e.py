"""完整的端到端测试：在干净临时目录中验证所有功能"""
import os
import sys
import tempfile
import csv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from click.testing import CliRunner
from papertool.cli import cli


def main():
    tmpdir = tempfile.mkdtemp(prefix="papertool_clean_")
    db_path = os.path.join(tmpdir, "db.json")
    log_dir = os.path.join(tmpdir, "logs")
    papers_dir = os.path.join(tmpdir, "papers")
    os.makedirs(papers_dir)

    for i, name in enumerate(["A - Survey on AI.pdf", "paper2.pdf", "2021_Bob_ML.pdf"]):
        p = os.path.join(papers_dir, name)
        with open(p, "wb") as f:
            f.write(b"%PDF-1.4\n%%EOF\n" + b"x" * (i * 100))

    print("临时目录:", tmpdir)
    print("初始文件:", os.listdir(papers_dir))
    print()

    runner = CliRunner()

    def run(args):
        r = runner.invoke(cli, ["--db-path", db_path, "--log-dir", log_dir] + args)
        print(f"$ papertool {' '.join(args)}")
        print(r.output.rstrip())
        if r.exit_code != 0:
            print(f"[exit {r.exit_code}]")
            if r.exception:
                import traceback
                traceback.print_exception(type(r.exception), r.exception, r.exception.__traceback__)
        print()
        return r

    # 1. scan
    run(["scan", papers_dir])

    # 2. list
    run(["list"])

    # 3. rename --all
    run(["rename", "--all"])
    print("rename 后文件:", os.listdir(papers_dir))

    # 4. list (检查数据库路径同步)
    run(["list"])

    # 5. export csv - 验证路径指向真实文件
    csv_path = os.path.join(tmpdir, "out.csv")
    run(["export", csv_path, "--format", "csv"])
    all_exists = True
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            exists = os.path.exists(row["file_path"])
            print(f"  CSV path exists: {exists} - {os.path.basename(row['file_path'])}")
            if not exists:
                all_exists = False
    assert all_exists, "rename 后导出 CSV 的文件路径应都存在"
    print("✓ rename 后所有 CSV 路径存在")
    print()

    # 6. rollback rename (3 steps)
    run(["rollback", "--steps", "3"])
    print("rollback 后文件:", os.listdir(papers_dir))
    run(["list"])

    # 7. tag: 设置元数据
    first_pdf = None
    for f in os.listdir(papers_dir):
        if f.lower().endswith(".pdf"):
            first_pdf = os.path.join(papers_dir, f)
            break
    print("tag 文件:", first_pdf)
    run([
        "tag",
        "--add-tags", "ai",
        "--add-tags", "survey",
        "--topic", "AI研究",
        "--status", "read",
        "--doi", "10.9999/test",
        "--journal", "Nature",
        "--keyword", "transformer",
        first_pdf,
    ])
    run(["list"])

    # 8. export bibtex
    bib_path = os.path.join(tmpdir, "after_tag.bib")
    run(["export", bib_path, "--format", "bibtex"])
    bib_content = open(bib_path, encoding="utf-8").read()
    print("BibTeX 片段:")
    print(bib_content[:400])
    assert "Nature" in bib_content
    assert "10.9999/test" in bib_content
    assert "transformer" in bib_content
    print("✓ tag 后 BibTeX 包含元数据")
    print()

    # 9. rollback metadata (1 step)
    run(["rollback", "--steps", "1"])
    bib_path2 = os.path.join(tmpdir, "after_rollback.bib")
    run(["export", bib_path2, "--format", "bibtex"])
    bib2 = open(bib_path2, encoding="utf-8").read()
    print("回滚后 BibTeX 片段:")
    print(bib2[:400])
    assert "Nature" not in bib2
    assert "10.9999/test" not in bib2
    print("✓ 元数据回滚成功，BibTeX 中已无 Nature/DOI")
    print()

    # 10. organize 预演
    run(["tag", "--topic", "AI研究", first_pdf])
    run(["organize", "--base-dir", papers_dir, "--dry-run", "-y"])
    print("dry-run 后文件:", os.listdir(papers_dir))
    assert any(f.lower().endswith(".pdf") for f in os.listdir(papers_dir)), "dry-run 不应移动文件"
    print("✓ organize dry-run 正确")
    print()

    # 11. organize 实际执行
    run(["organize", "--base-dir", papers_dir, "-y"])
    print("organize 后目录结构:")
    for root, dirs, files in os.walk(papers_dir):
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), papers_dir)
            print(" ", rel)
    assert os.path.isdir(os.path.join(papers_dir, "AI研究")), "应创建 AI研究 子目录"
    run(["list"])

    # 12. export csv 验证路径更新
    csv2 = os.path.join(tmpdir, "after_organize.csv")
    run(["export", csv2, "--format", "csv"])
    with open(csv2, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            exists = os.path.exists(row["file_path"])
            print(f"  CSV path exists: {exists} - {row['file_path'][-60:]}")
            assert exists, "organize 后 CSV 路径应存在"

    # 13. rollback organize
    run(["rollback", "--steps", "1"])
    print("rollback organize 后文件:", os.listdir(papers_dir))
    run(["list"])

    print("=" * 60)
    print("所有端到端测试通过！✓")
    print("=" * 60)
    print("临时目录保留用于检查:", tmpdir)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
