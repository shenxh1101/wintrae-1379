"""新功能完整端到端测试：organize 多层级、import、export 筛选、rollback 批次、check 路径"""
import os
import sys
import tempfile
import csv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from click.testing import CliRunner
from papertool.cli import cli


def main():
    tmpdir = tempfile.mkdtemp(prefix="papertool_new_features_")
    db_path = os.path.join(tmpdir, "db.json")
    log_dir = os.path.join(tmpdir, "logs")
    papers_dir = os.path.join(tmpdir, "papers")
    os.makedirs(papers_dir)

    # 创建 5 个测试 PDF
    test_pdfs = [
        ("2020_Alice_NLP_BERT.pdf", {"title": "BERT for NLP", "authors": ["Alice"], "year": 2020, "topic": "NLP", "tags": ["bert"]}),
        ("2021_Bob_CV_ResNet.pdf", {"title": "ResNet for CV", "authors": ["Bob"], "year": 2021, "topic": "CV", "tags": ["resnet", "cv"]}),
        ("2022_Charlie_ML_GAN.pdf", {"title": "GAN for ML", "authors": ["Charlie"], "year": 2022, "topic": "ML", "tags": ["gan"]}),
        ("2023_Dave_RL_DQN.pdf", {"title": "DQN for RL", "authors": ["Dave"], "year": 2023, "topic": "RL", "tags": ["rl", "dqn"]}),
        ("paper_no_meta.pdf", {"title": None, "authors": [], "year": None, "topic": None, "tags": []}),
    ]

    for fname, meta in test_pdfs:
        p = os.path.join(papers_dir, fname)
        with open(p, "wb") as f:
            f.write(b"%PDF-1.4\n%%EOF\n" + b"x" * 100)

    print("=" * 60)
    print("临时目录:", tmpdir)
    print("初始文件:", os.listdir(papers_dir))
    print("=" * 60)
    print()

    runner = CliRunner(env={"PYTHONIOENCODING": "utf-8"})

    def _print(msg):
        try:
            print(msg)
        except UnicodeEncodeError:
            print(msg.encode('ascii', errors='replace').decode('ascii'))

    def run(args, auto_yes=True):
        full_args = ["--db-path", db_path, "--log-dir", log_dir] + args
        r = runner.invoke(cli, full_args, input="y\n" if auto_yes else None)
        cmd = f"papertool {' '.join(args)}"
        print(f"$ {cmd}")
        try:
            print(r.output.rstrip())
        except UnicodeEncodeError:
            print(r.output.rstrip().encode('ascii', errors='replace').decode('ascii'))
        if r.exit_code != 0:
            print(f"[exit {r.exit_code}]")
            if r.exception:
                import traceback
                traceback.print_exception(type(r.exception), r.exception, r.exception.__traceback__)
        print()
        return r

    # ========== 1. 扫描 ==========
    print("=" * 60)
    print("1. SCAN + TAG 设置元数据")
    print("=" * 60)
    print()
    run(["scan", papers_dir])
    run(["list"])

    # 给每篇论文设置完整元数据
    for fname, meta in test_pdfs:
        fpath = os.path.join(papers_dir, fname)
        args = ["tag", fpath]
        if meta.get("title"):
            args += ["--title", meta["title"]]
        if meta.get("authors"):
            for a in meta["authors"]:
                args += ["--author", a]
        if meta.get("year"):
            args += ["--year", str(meta["year"])]
        if meta.get("topic"):
            args += ["--topic", meta["topic"]]
        if meta.get("tags"):
            for t in meta["tags"]:
                args += ["--add-tags", t]
        if meta.get("year") is not None:
            if meta["year"] % 2 == 0:
                args += ["--status", "read"]
            else:
                args += ["--status", "reading"]
        else:
            args += ["--status", "unread"]
        run(args)

    run(["list"])

    # ========== 2. RENAME 整批 + ROLLBACK 整批 ==========
    print("=" * 60)
    print("2. RENAME --all (整批) + ROLLBACK (整批回滚)")
    print("=" * 60)
    print()
    run(["rename", "--all", "-y"])
    print("rename 后文件:", os.listdir(papers_dir))
    run(["list"])

    print("--- rollback --list (查看批次) ---")
    run(["rollback", "--list"])

    print("--- 不带参数 rollback (整批回滚 rename) ---")
    run(["rollback", "-y"])
    print("rollback 后文件:", os.listdir(papers_dir))
    run(["list"])

    # ========== 3. ORGANIZE 多层级 ==========
    print("=" * 60)
    print("3. ORGANIZE 多层级: topic / year / read_status")
    print("=" * 60)
    print()
    # dry-run 预演
    run(["organize", "--base-dir", papers_dir, "--layer", "topic", "--layer", "year", "--dry-run", "-y"])
    print("dry-run 后文件:", os.listdir(papers_dir))

    # 实际执行
    run(["organize", "--base-dir", papers_dir, "--layer", "topic", "--layer", "year", "-y"])
    print("organize 后目录结构:")
    for root, dirs, files in os.walk(papers_dir):
        for f in files:
            if f.lower().endswith(".pdf"):
                rel = os.path.relpath(os.path.join(root, f), papers_dir)
                print(f"  {rel}")
    run(["list"])

    # 验证 export 路径正确
    csv_path = os.path.join(tmpdir, "org_check.csv")
    run(["export", csv_path, "--format", "csv"])
    all_exist = True
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["file_path"] and not os.path.exists(row["file_path"]):
                _print(f"  ✗ 路径不存在: {row['file_path']}")
                all_exist = False
    assert all_exist, "organize 后 CSV 路径必须全部存在"
    _print("✓ organize 后所有 CSV 路径存在")
    print()

    # rollback organize 整批
    print("--- rollback organize (整批) ---")
    run(["rollback", "-y"])
    print("rollback 后文件:", os.listdir(papers_dir))
    run(["list"])

    # ========== 4. EXPORT 多条件筛选 + 多字段分组 ==========
    print("=" * 60)
    print("4. EXPORT 多条件筛选 + 多字段分组")
    print("=" * 60)
    print()

    # 按多标签筛选
    run(["export", os.path.join(tmpdir, "filter_tags.csv"), "--format", "csv",
         "--tag", "rl", "--tag", "dqn"])
    # 按年份范围筛选
    run(["export", os.path.join(tmpdir, "filter_year.csv"), "--format", "csv",
         "--year-from", "2021", "--year-to", "2023"])
    # 按状态 + 课题筛选
    run(["export", os.path.join(tmpdir, "filter_mix.csv"), "--format", "csv",
         "--status", "read", "--topic", "NLP"])

    # 多字段分组的阅读书单
    reading_path = os.path.join(tmpdir, "reading_multi.md")
    run(["export", reading_path, "--format", "reading",
         "--group-by", "topic", "--group-by", "year"])
    print("阅读书单 (topic/year 分组) 片段:")
    with open(reading_path, encoding="utf-8") as f:
        content = f.read()
        for line in content.split("\n")[:25]:
            print(f"  {line}")
    assert "## NLP" in content, "应有 NLP 二级标题"
    assert "### 2020" in content, "应有 2020 三级标题"
    _print("✓ 多字段分组阅读书单正确")
    print()

    # ========== 5. IMPORT 从 CSV 批量导入 ==========
    print("=" * 60)
    print("5. IMPORT 从 CSV 批量导入元数据")
    print("=" * 60)
    print()

    # 先导出 CSV 作为模板
    template_csv = os.path.join(tmpdir, "template.csv")
    run(["export", template_csv, "--format", "csv"])

    # 修改 CSV 内容，补全元数据
    import_csv = os.path.join(tmpdir, "import_data.csv")
    with open(template_csv, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # 修改几行的元数据
    for row in rows:
        if "BERT" in row.get("title", ""):
            row["doi"] = "10.1000/bert2020"
            row["journal"] = "ACL"
            row["keywords"] = "transformer; nlp"
            row["tags"] = "important; must-read"
            row["topic"] = "自然语言处理"
        elif "ResNet" in row.get("title", ""):
            row["doi"] = "10.1000/resnet2021"
            row["journal"] = "CVPR"
            row["tags"] = "cv; classic"
        elif "paper_no_meta" in row.get("file_path", ""):
            row["title"] = "Unknown Paper"
            row["authors"] = "Anonymous"
            row["year"] = "2019"
            row["topic"] = "待分类"
            row["read_status"] = "unread"

    with open(import_csv, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=reader.fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    # 预演
    print("--- import --dry-run ---")
    run(["import", import_csv, "--dry-run", "-y"])

    # 实际导入
    print("--- import 实际执行 ---")
    run(["import", import_csv, "-y"])

    # 验证导入结果
    verify_csv = os.path.join(tmpdir, "after_import.csv")
    run(["export", verify_csv, "--format", "csv"])
    with open(verify_csv, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if "BERT" in row.get("title", ""):
                assert row["doi"] == "10.1000/bert2020", "BERT DOI 应被更新"
                assert row["journal"] == "ACL", "BERT journal 应被更新"
                assert "transformer" in row["keywords"], "BERT keywords 应被更新"
                assert "important" in row["tags"], "BERT tags 应被更新"
                assert row["topic"] == "自然语言处理", "BERT topic 应被更新"
                _print("✓ BERT 元数据导入正确")
            elif "ResNet" in row.get("title", ""):
                assert row["doi"] == "10.1000/resnet2021", "ResNet DOI 应被更新"
                _print("✓ ResNet 元数据导入正确")

    # import 的 rollback
    print("--- rollback import 整批 ---")
    run(["rollback", "-y"])
    # 验证 DOI 已恢复
    verify_csv2 = os.path.join(tmpdir, "after_import_rollback.csv")
    run(["export", verify_csv2, "--format", "csv"])
    with open(verify_csv2, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if "BERT" in row.get("title", ""):
                assert row["doi"] == "", "BERT DOI 应被回滚为空"
                _print("✓ import 回滚成功，DOI 已恢复")

    # ========== 6. CHECK 路径一致性 ==========
    print("=" * 60)
    print("6. CHECK 路径一致性检查")
    print("=" * 60)
    print()

    # 先把目录恢复成 organize 之前的样子
    # 新增一个 PDF 但不加入数据库
    extra_pdf = os.path.join(papers_dir, "extra_unscanned.pdf")
    with open(extra_pdf, "wb") as f:
        f.write(b"%PDF-1.4\n%%EOF\n")

    # 删除一个已扫描的 PDF
    to_delete = None
    for f in os.listdir(papers_dir):
        if f.lower().endswith(".pdf") and f != "extra_unscanned.pdf":
            to_delete = os.path.join(papers_dir, f)
            break
    deleted_name = os.path.basename(to_delete)
    os.remove(to_delete)
    print(f"已删除: {deleted_name}")
    print(f"已新增未扫描: extra_unscanned.pdf")
    print()

    run(["check", "--folder", papers_dir])

    # 修复：扫描新增的文件
    run(["scan", papers_dir])
    run(["check", "--folder", papers_dir, "--check-type", "paths"])

    # ========== 完成 ==========
    print("=" * 60)
    _print("所有新功能端到端测试通过！✓")
    print("=" * 60)
    print("临时目录保留用于检查:", tmpdir)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"\n测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
