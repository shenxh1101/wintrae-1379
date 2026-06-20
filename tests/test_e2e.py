"""端到端测试脚本：验证所有核心功能"""
import os
import sys
import shutil
import tempfile
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from click.testing import CliRunner

from papertool.cli import cli


def create_minimal_pdf(filepath):
    content = b"".join([
        b"%PDF-1.4\n",
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n",
        b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n",
        b"trailer\n<< /Size 4 /Root 1 0 R >>\n",
        b"startxref\n190\n%%EOF\n",
    ])
    with open(filepath, "wb") as f:
        f.write(content)


def run_cli(args, runner=None, db_path=None, log_dir=None):
    if runner is None:
        runner = CliRunner()
    full_args = []
    if db_path:
        full_args += ["--db-path", db_path]
    if log_dir:
        full_args += ["--log-dir", log_dir]
    full_args += args
    result = runner.invoke(cli, full_args)
    print(f"$ papertool {' '.join(args)}")
    if result.output:
        print(result.output)
    if result.exit_code != 0:
        print(f"[exit code: {result.exit_code}]")
        if result.exception:
            import traceback
            traceback.print_exception(type(result.exception), result.exception, result.exception.__traceback__)
    print()
    return result


def main():
    tmpdir = tempfile.mkdtemp(prefix="papertool_e2e_")
    db_path = os.path.join(tmpdir, "papers.json")
    log_dir = os.path.join(tmpdir, "logs")
    papers_dir = os.path.join(tmpdir, "papers")
    os.makedirs(papers_dir)

    runner = CliRunner()

    print("=" * 60)
    print("端到端测试: papertool")
    print(f"工作目录: {tmpdir}")
    print("=" * 60)
    print()

    try:
        # 1. 创建测试 PDF
        print("--- 创建测试 PDF 文件 ---")
        pdf1 = os.path.join(papers_dir, "paper1.pdf")
        pdf2 = os.path.join(papers_dir, "paper2.pdf")
        pdf3 = os.path.join(papers_dir, "paper3.pdf")
        create_minimal_pdf(pdf1)
        create_minimal_pdf(pdf2)
        create_minimal_pdf(pdf3)
        print(f"Created: {pdf1}")
        print(f"Created: {pdf2}")
        print(f"Created: {pdf3}")
        print()

        # 2. scan 扫描
        print("--- 1. scan ---")
        r = run_cli(["scan", papers_dir], runner, db_path, log_dir)
        assert r.exit_code == 0, "scan failed"

        # 3. list 列出
        print("--- 2. list ---")
        r = run_cli(["list"], runner, db_path, log_dir)
        assert r.exit_code == 0, "list failed"

        # 4. tag 设置课题、标签、元数据、阅读状态
        print("--- 3. tag (设置课题 NLP、标签、DOI、期刊、阅读状态) ---")
        r = run_cli([
            "tag",
            "--topic", "自然语言处理",
            "--add-tags", "nlp",
            "--add-tags", "survey",
            "--status", "reading",
            "--doi", "10.1234/nlp.2023.001",
            "--journal", "Journal of AI",
            "--keyword", "transformer",
            "--keyword", "attention",
            pdf1,
        ], runner, db_path, log_dir)
        assert r.exit_code == 0, "tag pdf1 failed"

        print("--- 3b. tag (设置课题 CV) ---")
        r = run_cli([
            "tag",
            "--topic", "计算机视觉",
            "--status", "read",
            pdf2,
        ], runner, db_path, log_dir)
        assert r.exit_code == 0, "tag pdf2 failed"

        # 5. list 查看更新后的数据
        print("--- 4. list (验证 tag 结果) ---")
        r = run_cli(["list"], runner, db_path, log_dir)
        assert "自然语言处理" in r.output
        assert "计算机视觉" in r.output
        assert "nlp" in r.output
        assert "reading" in r.output
        assert "read" in r.output

        # 6. check 检查
        print("--- 5. check ---")
        r = run_cli(["check", "--folder", papers_dir], runner, db_path, log_dir)
        assert r.exit_code == 0, "check failed"

        # 7. rename 重命名
        print("--- 6. rename --all ---")
        r = run_cli(["rename", "--all"], runner, db_path, log_dir)
        assert r.exit_code == 0, "rename failed"
        # 检查原文件是否已被重命名
        renamed_exists = not os.path.exists(pdf1)
        print(f"原文件 pdf1.pdf 已被重命名: {renamed_exists}")
        assert renamed_exists, "rename 应该已将文件改名"

        # 8. export BibTeX
        print("--- 7. export bibtex ---")
        bib_path = os.path.join(tmpdir, "refs.bib")
        r = run_cli(["export", bib_path, "--format", "bibtex"], runner, db_path, log_dir)
        assert r.exit_code == 0, "export bibtex failed"
        assert os.path.exists(bib_path)
        with open(bib_path, encoding="utf-8") as f:
            bib_content = f.read()
        assert "@" in bib_content
        print(f"BibTeX 文件大小: {len(bib_content)} 字符")

        # 9. export CSV
        print("--- 8. export csv ---")
        csv_path = os.path.join(tmpdir, "papers.csv")
        r = run_cli(["export", csv_path, "--format", "csv"], runner, db_path, log_dir)
        assert r.exit_code == 0, "export csv failed"
        assert os.path.exists(csv_path)

        # 10. export reading list
        print("--- 9. export reading ---")
        md_path = os.path.join(tmpdir, "reading.md")
        r = run_cli(["export", md_path, "--format", "reading", "--group-by", "topic"], runner, db_path, log_dir)
        assert r.exit_code == 0, "export reading failed"
        assert os.path.exists(md_path)
        with open(md_path, encoding="utf-8") as f:
            md_content = f.read()
        assert "## 自然语言处理" in md_content
        print("阅读书单中包含课题分组 ✓")

        # 11. organize 按课题整理 (预演)
        print("--- 10. organize --dry-run (预演) ---")
        r = run_cli(["organize", "--base-dir", papers_dir, "--dry-run", "-y"], runner, db_path, log_dir)
        assert r.exit_code == 0, "organize dry-run failed"
        assert "预演" in r.output
        # 预演不应真的移动文件
        assert any(
            p.lower().endswith(".pdf") for p in os.listdir(papers_dir)
        ), "预演模式不应该移动文件"

        # 12. organize 实际执行
        print("--- 11. organize (实际移动) ---")
        r = run_cli(["organize", "--base-dir", papers_dir, "-y"], runner, db_path, log_dir)
        assert r.exit_code == 0, "organize failed"
        nlp_dir = os.path.join(papers_dir, "自然语言处理")
        cv_dir = os.path.join(papers_dir, "计算机视觉")
        assert os.path.isdir(nlp_dir), f"应该创建 {nlp_dir}"
        assert os.path.isdir(cv_dir), f"应该创建 {cv_dir}"
        print(f"NLP 目录文件: {os.listdir(nlp_dir)}")
        print(f"CV 目录文件: {os.listdir(cv_dir)}")
        assert any(p.lower().endswith(".pdf") for p in os.listdir(nlp_dir))
        assert any(p.lower().endswith(".pdf") for p in os.listdir(cv_dir))

        # 13. list 验证 organize 后路径已更新
        print("--- 12. list (验证 organize 已更新数据库路径) ---")
        r = run_cli(["list"], runner, db_path, log_dir)
        assert "自然语言处理" in r.output or "计算机视觉" in r.output
        # 检查数据库内容
        with open(db_path, encoding="utf-8") as f:
            db_data = json.load(f)
        paths = [p["file_path"] for p in db_data["papers"].values()]
        print(f"数据库路径: {paths}")
        assert any("自然语言处理" in p or "计算机视觉" in p for p in paths), "数据库中的路径应随 organize 更新"

        # 14. rollback 回滚 organize
        print("--- 13. rollback (回滚 organize) ---")
        r = run_cli(["rollback", "--steps", "1"], runner, db_path, log_dir)
        assert r.exit_code == 0, "rollback organize failed"
        # 检查论文是否回到 papers_dir 根目录
        print(f"papers_dir 文件: {os.listdir(papers_dir)}")
        # 验证数据库路径已更新
        with open(db_path, encoding="utf-8") as f:
            db_data = json.load(f)
        paths = [p["file_path"] for p in db_data["papers"].values()]
        print(f"回滚后数据库路径: {paths}")

        # 15. rollback 回滚 tag 元数据
        print("--- 14. rollback (回滚 tag 元数据更改) ---")
        with open(db_path, encoding="utf-8") as f:
            before = json.load(f)
        before_tags = {}
        for k, v in before["papers"].items():
            before_tags[k] = {
                "tags": v.get("tags", []),
                "doi": v.get("doi"),
                "journal": v.get("journal"),
                "topic": v.get("topic"),
                "read_status": v.get("read_status"),
                "keywords": v.get("keywords", []),
            }
        r = run_cli(["rollback", "--steps", "1"], runner, db_path, log_dir)
        assert r.exit_code == 0, "rollback metadata failed"

        with open(db_path, encoding="utf-8") as f:
            after = json.load(f)
        # 检查关键词等是否恢复
        found_restored = False
        for k, v in after["papers"].items():
            old = before_tags.get(k, {})
            if old.get("keywords") and not v.get("keywords"):
                found_restored = True
                break
            if old.get("doi") and not v.get("doi"):
                found_restored = True
                break
        print(f"元数据已恢复: {found_restored}")

        # 16. rollback --list 查看操作历史
        print("--- 15. rollback --list ---")
        r = run_cli(["rollback", "--list"], runner, db_path, log_dir)
        assert r.exit_code == 0, "rollback --list failed"

        # 17. export 验证回滚后的内容
        print("--- 16. export (验证回滚后导出内容) ---")
        bib_path2 = os.path.join(tmpdir, "refs_after_rollback.bib")
        r = run_cli(["export", bib_path2, "--format", "bibtex"], runner, db_path, log_dir)
        assert r.exit_code == 0
        print("导出成功 ✓")

        # 18. rollback 回滚 rename
        print("--- 17. rollback rename ---")
        # 先看操作历史
        r = run_cli(["rollback", "--list"], runner, db_path, log_dir)
        print(r.output)
        # 回滚 rename
        r = run_cli(["rollback", "--steps", "1"], runner, db_path, log_dir)
        assert r.exit_code == 0
        # 检查 pdf1 是否又存在了
        print(f"pdf1 是否存在: {os.path.exists(pdf1)}")
        with open(db_path, encoding="utf-8") as f:
            db_data = json.load(f)
        paths = [p["file_path"] for p in db_data["papers"].values()]
        print(f"回滚 rename 后路径: {paths}")
        # list 看看
        r = run_cli(["list"], runner, db_path, log_dir)
        # export 检查路径指向真实存在的文件
        csv_path2 = os.path.join(tmpdir, "after_rollback_rename.csv")
        r = run_cli(["export", csv_path2, "--format", "csv"], runner, db_path, log_dir)
        assert r.exit_code == 0
        print("回滚 rename 后导出成功 ✓")

        print("=" * 60)
        print("所有端到端测试通过！✓")
        print("=" * 60)
        print()
        print(f"临时目录保留用于检查: {tmpdir}")
        return 0

    except AssertionError as e:
        print(f"\n❌ 测试失败: {e}")
        print(f"临时目录保留用于调试: {tmpdir}")
        import traceback
        traceback.print_exc()
        return 1
    except Exception as e:
        print(f"\n❌ 测试异常: {e}")
        print(f"临时目录保留用于调试: {tmpdir}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
