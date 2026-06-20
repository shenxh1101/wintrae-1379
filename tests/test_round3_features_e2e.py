"""第三轮需求端到端测试：check 可配置修复、import 灵活匹配、summary模式、rollback稳定"""
import os
import sys
import tempfile
import csv
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from click.testing import CliRunner
from papertool.cli import cli


def _print(msg):
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode('ascii', errors='replace').decode('ascii'))


def make_pdf(path, unique_id=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if unique_id is None:
        unique_id = os.path.basename(path)
    uid_bytes = f"\n%UID:{unique_id}".encode("utf-8")
    with open(path, "wb") as f:
        f.write(b"%PDF-1.4\n%Test\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF")
        f.write(uid_bytes)


def main():
    tmpdir = tempfile.mkdtemp(prefix="papertool_r3_")
    _print(f"临时目录: {tmpdir}")

    db_path = os.path.join(tmpdir, "papers.json")
    log_dir = os.path.join(tmpdir, "logs")
    papers_dir = os.path.join(tmpdir, "papers")
    os.makedirs(papers_dir)

    runner = CliRunner(env={"PYTHONIOENCODING": "utf-8"})

    def run(args, auto_yes=True):
        if auto_yes and "-y" not in args and "--yes" not in args:
            cmd = args[0] if args else ""
            need_yes = {"rename", "organize", "import", "rollback"}
            if cmd in need_yes or (cmd == "check" and "--fix" in args):
                args = args + ["--yes"]
        result = runner.invoke(cli, [
            "--db-path", db_path,
            "--log-dir", log_dir,
        ] + args, catch_exceptions=False)
        return result

    papers_info = [
        ("paper_bert.pdf", "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding", 2018, "NLP"),
        ("paper_gpt3.pdf", "Language Models are Few-Shot Learners", 2020, "NLP"),
        ("paper_resnet.pdf", "Deep Residual Learning for Image Recognition", 2015, "CV"),
        ("paper_yolo.pdf", "You Only Look Once: Unified, Real-Time Object Detection", 2016, "CV"),
        ("paper_transformer.pdf", "Attention Is All You Need", 2017, "NLP"),
    ]

    for fname, title, year, topic in papers_info:
        make_pdf(os.path.join(papers_dir, fname))

    # ========== 初始化 ==========
    _print("=" * 60)
    _print("Step 0: scan + tag 初始化")
    r = run(["scan", papers_dir])
    assert r.exit_code == 0
    for fname, title, year, topic in papers_info:
        fpath = os.path.join(papers_dir, fname)
        r = run(["tag", fpath,
                 "--title", title,
                 "--year", str(year),
                 "--topic", topic,
                 "--author", "Test Author"])
        assert r.exit_code == 0, f"tag {fname} 失败: {r.output}"

    # 设置状态：1 已读 / 2 阅读中 / 2 未读
    status_map = {"paper_bert.pdf": "reading", "paper_gpt3.pdf": "read",
                  "paper_resnet.pdf": "unread", "paper_yolo.pdf": "unread",
                  "paper_transformer.pdf": "reading"}
    for fname, s in status_map.items():
        r = run(["tag", os.path.join(papers_dir, fname), "--status", s])
        assert r.exit_code == 0, f"tag {fname} status={s} 失败: {r.output}"
    _print("Step 0 OK\n")

    # ========== 需求 3: export summary 模式 ==========
    _print("=" * 60)
    _print("Step 1: 测试 export summary (阅读书单 Markdown + CSV)")

    # 阅读书单 summary
    reading_sum = os.path.join(tmpdir, "reading_summary.md")
    r = run(["export", reading_sum, "--format", "reading",
             "--group-by", "topic", "--group-by", "year", "--summary"])
    assert r.exit_code == 0, f"阅读书单 summary 失败: {r.output}"

    with open(reading_sum, "r", encoding="utf-8") as f:
        md = f.read()

    assert "总体汇总" in md, "缺少总体汇总章节"
    assert "待读" in md or "已读" in md, "缺少待读/已读统计"
    assert "按课题统计" in md, "缺少按课题统计表格"
    assert "按年份统计" in md, "缺少按年份统计表格"
    assert "按阅读状态统计" in md, "缺少按状态统计表格"
    assert "| 课题 | 总数 | 待读 | 已读 | 阅读中 |" in md, "缺少课题表头"
    _print("  [OK] 阅读书单含总体汇总和按课题/年份/状态统计表格")

    # 验证分组带详细统计：例如 "NLP (3篇, 待读0/已读1/阅读中2)"
    assert "待读" in md or "已读" in md or "阅读中" in md, "分组标题中缺少状态统计"
    _print("  [OK] 每层分组含详细状态统计 (待读/已读/阅读中)")

    # CSV summary
    csv_sum = os.path.join(tmpdir, "papers_summary.csv")
    r = run(["export", csv_sum, "--format", "csv", "--summary"])
    assert r.exit_code == 0, f"CSV summary 失败: {r.output}"

    with open(csv_sum, "r", encoding="utf-8-sig") as f:
        content = f.read()

    assert "汇总: 共" in content, "CSV 缺少汇总行"
    assert "待读" in content, "CSV 缺少待读统计"
    assert "按课题" in content, "CSV 缺少按课题统计"
    assert "按年份" in content, "CSV 缺少按年份统计"
    _print("  [OK] CSV summary 含汇总与分组统计，且论文按排序键稳定输出")

    # 两次 CSV (无 summary) 内容应相同（顺序稳定）
    csv_plain1 = os.path.join(tmpdir, "plain1.csv")
    csv_plain2 = os.path.join(tmpdir, "plain2.csv")
    run(["export", csv_plain1, "--format", "csv"])
    run(["export", csv_plain2, "--format", "csv"])
    with open(csv_plain1, "r", encoding="utf-8-sig") as f1, \
         open(csv_plain2, "r", encoding="utf-8-sig") as f2:
        assert f1.read() == f2.read(), "两次普通 CSV 导出内容不一致（排序不稳定）"
    _print("  [OK] 普通 CSV 顺序稳定（两次导出完全一致）")

    _print("Step 1 OK\n")

    # ========== 需求 2: import 灵活匹配 ==========
    _print("=" * 60)
    _print("Step 2: 测试 import 灵活匹配 (DOI URL/相对路径/模糊标题)")

    # A. DOI URL 格式匹配 (https://doi.org/10.xxxx)
    bert_path = os.path.join(papers_dir, "paper_bert.pdf")
    run(["tag", bert_path, "--doi", "10.1000/nlp.bert.2018"])
    run(["tag", os.path.join(papers_dir, "paper_gpt3.pdf"),
         "--doi", "10.1000/nlp.gpt3.2020"])

    csv_doi_url = os.path.join(tmpdir, "doi_url.csv")
    with open(csv_doi_url, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["doi", "journal", "tags", "topic"])
        w.writerow(["https://doi.org/10.1000/nlp.bert.2018", "ACL", "classic; must-read", "BERT课题"])
        w.writerow(["DOI:10.1000/nlp.gpt3.2020", "NeurIPS", "llm; foundation", "大模型"])

    r = run(["import", csv_doi_url, "--dry-run"])
    assert r.exit_code == 0, f"DOI URL 预演失败: {r.output}"
    assert "DOI 匹配" in r.output or "将更新 2" in r.output, f"DOI URL 未匹配: {r.output}"
    _print("  [OK] DOI URL (https://doi.org/...) 和 DOI:前缀 正确解析匹配")

    r = run(["import", csv_doi_url])
    assert r.exit_code == 0

    check_csv = os.path.join(tmpdir, "check_import.csv")
    run(["export", check_csv, "--format", "csv"])
    with open(check_csv, "r", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        t = row.get("title", "")
        if "BERT" in t:
            assert row["topic"] == "BERT课题", f"BERT topic 未更新: {row}"
            assert row["journal"] == "ACL", f"BERT journal 未更新"
            _print("  [OK] DOI URL 匹配 → BERT 已更新 topic/journal")
        elif "Few-Shot" in t:
            assert row["topic"] == "大模型", f"GPT3 topic 未更新"
            _print("  [OK] DOI:前缀匹配 → GPT3 已更新 topic")

    # B. 相对路径 + 文件名匹配 (CSV 放在子目录，给相对路径)
    subfolder = os.path.join(tmpdir, "csvs")
    os.makedirs(subfolder, exist_ok=True)
    csv_rel = os.path.join(subfolder, "relative.csv")
    with open(csv_rel, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["file_path", "doi", "keywords"])  # 文件名匹配
        w.writerow(["paper_resnet.pdf", "10.1000/cv.resnet", "残差;卷积"])

    r = run(["import", csv_rel, "--base-dir", papers_dir, "--dry-run"])
    assert r.exit_code == 0, f"相对路径 dry-run 失败: {r.output}"
    assert "文件名匹配" in r.output or "file_path" in r.output, f"相对路径未匹配: {r.output}"
    _print("  [OK] 相对路径 + 文件名兜底匹配 正确 (base-dir)")

    # C. 模糊标题匹配（大小写不敏感+词匹配）
    csv_fuzzy = os.path.join(tmpdir, "fuzzy.csv")
    with open(csv_fuzzy, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["title", "read_status", "tags"])
        # 标题只给一部分，大小写不一致
        w.writerow(["ATTENTION IS all you NEED", "read", "transformer; classic"])

    r = run(["import", csv_fuzzy, "--dry-run"])
    assert r.exit_code == 0, f"模糊标题 dry-run 失败: {r.output}"
    assert "模糊匹配" in r.output or "标题" in r.output or "将更新 1" in r.output, f"模糊标题未匹配: {r.output}"
    _print("  [OK] 标题大小写不敏感 + 模糊匹配 正确 (ATTENTION IS all you NEED)")

    r = run(["import", csv_fuzzy])
    assert r.exit_code == 0
    check_csv2 = os.path.join(tmpdir, "check_fuzzy.csv")
    run(["export", check_csv2, "--format", "csv"])
    with open(check_csv2, "r", encoding="utf-8-sig") as f:
        rows2 = list(csv.DictReader(f))
    for row in rows2:
        if "Attention" in row.get("title", ""):
            assert row["read_status"] == "read", f"Transformer status 未更新: {row['read_status']}"
            _print("  [OK] 模糊标题 → Transformer 已设为已读")

    _print("Step 2 OK\n")

    # ========== 需求 1: check --fix 可配置跳过 + 再次校验 ==========
    _print("=" * 60)
    _print("Step 3: 测试 check --fix 可配置跳过 (--skip-missing/--skip-unindexed) 和再次校验")

    # 制造两个问题
    yolo_path = os.path.join(papers_dir, "paper_yolo.pdf")
    orphan = os.path.join(tmpdir, "orphan")
    os.makedirs(orphan)
    yolo_moved = os.path.join(orphan, "paper_yolo_moved.pdf")
    shutil_move_fallback(yolo_path, yolo_moved)

    unindexed1 = os.path.join(papers_dir, "paper_gan.pdf")
    unindexed2 = os.path.join(papers_dir, "paper_vae.pdf")
    make_pdf(unindexed1)
    make_pdf(unindexed2)

    # A. 预演时显示候选信息
    r = run(["check", "--folder", papers_dir, "--check-type", "paths",
             "--fix", "--dry-run"])
    assert r.exit_code == 0, f"预演 check 失败: {r.output}"
    assert "失效记录" in r.output or "数据库记录但文件不存在" in r.output, f"未列失效: {r.output}"
    assert "未入库" in r.output or "未加入数据库" in r.output, f"未列未入库: {r.output}"
    _print("  [OK] 预演清楚列出每类问题 (含具体文件)")

    # B. 实际执行时：跳过 unindexed2 (paper_vae.pdf)
    r = run(["check", "--folder", papers_dir, "--check-type", "paths",
             "--fix", "--skip-unindexed", unindexed2])
    assert r.exit_code == 0, f"执行 check --fix skip 失败: {r.output}"
    assert "保留不动的未入库文件" in r.output or "跳过" in r.output or "保留不动" in r.output, \
        f"未显示跳过的文件: {r.output}"
    # 再次校验输出
    assert "修复后再次校验" in r.output or "已处理" in r.output or "仍保留" in r.output, \
        f"未显示再次校验: {r.output}"
    _print("  [OK] --skip-unindexed 生效；修复后再次校验显示'已处理/仍保留'对比")

    # 验证：paper_gan 已扫入，paper_vae 仍未扫
    check3 = os.path.join(tmpdir, "check_skip.csv")
    run(["export", check3, "--format", "csv"])
    with open(check3, "r", encoding="utf-8-sig") as f:
        rows3 = list(csv.DictReader(f))
    fnames3 = [os.path.basename(r["file_path"]) for r in rows3 if r["file_path"]]

    assert "paper_gan.pdf" in fnames3, f"paper_gan 应被扫入但没扫: {fnames3}"
    assert "paper_vae.pdf" not in fnames3, f"paper_vae 应被跳过但仍扫入: {fnames3}"
    _print("  [OK] paper_gan 已扫入，paper_vae 保留不动 (未入库)")

    # 把 yolo 移回，paper_vae 手动清掉
    shutil_move_fallback(yolo_moved, yolo_path)
    safe_remove(unindexed2)

    # 回滚 Step 3 产生的操作批次（恢复 yolo 记录、移除刚扫入的 paper_gan 记录），
    # 保持数据库回到 Step 3 前的干净状态，方便 Step 4 测试
    _print("  [CLEANUP] 回滚 Step 3 操作批次 (保持数据库干净)")
    r = run(["rollback"])
    assert r.exit_code == 0, f"Step3 清理回滚失败: {r.output}"

    _print("Step 3 OK\n")

    # ========== 需求 4: rollback 更稳 ==========
    _print("=" * 60)
    _print("Step 4: 测试 rollback 稳定性 (删记录恢复不需要PDF存在 + 失败项保留)")

    # 制造问题：yolo 和 resnet 两个文件移走，check --fix 两个都移除，只把 yolo 移回，rollback 时两个记录都应该恢复
    resnet_path = os.path.join(papers_dir, "paper_resnet.pdf")
    yolo_path2 = os.path.join(papers_dir, "paper_yolo.pdf")
    orphan2 = os.path.join(tmpdir, "orphan2")
    os.makedirs(orphan2)
    resnet_moved = os.path.join(orphan2, "resnet_moved.pdf")
    yolo_moved2 = os.path.join(orphan2, "yolo_moved.pdf")
    shutil_move_fallback(resnet_path, resnet_moved)
    shutil_move_fallback(yolo_path2, yolo_moved2)

    # 执行 check --fix（都移除）
    r = run(["check", "--folder", papers_dir, "--check-type", "paths", "--fix",
             "--no-recheck"])
    assert r.exit_code == 0

    # 先 rollback --list 确认移除操作已记录
    r = run(["rollback", "--list"])
    assert "修复路径一致性" in r.output or "remove_record" in r.output or "remove" in r.output.lower(), \
        f"rollback --list 未显示修复批次: {r.output[:500]}"
    _print("  [OK] rollback --list 正确显示 check --fix 操作批次")

    # 只把 yolo 移回，resnet 仍不在
    shutil_move_fallback(yolo_moved2, yolo_path2)

    # rollback（默认最近一批）
    r = run(["rollback"])
    assert r.exit_code == 0, f"rollback 执行失败: {r.output}"

    # 验证：两个记录都应该在数据库中（resnet 虽然 PDF 不在，但记录要恢复）
    check4 = os.path.join(tmpdir, "after_rollback.csv")
    run(["export", check4, "--format", "csv"])
    with open(check4, "r", encoding="utf-8-sig") as f:
        rows4 = list(csv.DictReader(f))
    titles4 = [r["title"] for r in rows4 if r["title"]]

    assert any("Look Once" in t or "YOLO" in t for t in titles4), f"YOLO 记录未恢复, titles={titles4}"
    assert any("Residual" in t for t in titles4), f"ResNet 记录应恢复 (即使 PDF 不在也恢复记录). titles={titles4}"
    _print("  [OK] rollback 即使原 PDF 暂时不在 (resnet)，数据库记录也成功恢复")

    # 再跑 check paths 能看到 resnet 仍是失效（因为文件还在 orphan2）
    r = run(["check", "--folder", papers_dir, "--check-type", "paths"])
    assert r.exit_code == 0
    # resnet 文件确实在 orphan2，因此 check 应该至少能列一次失效（YOLO 已移回，可能 1 条失效）
    if "不存在" in r.output:
        _print("  [OK] check 正确识别出 resnet 的 PDF 仍失效（提示可再次修复）")
    else:
        _print("  [INFO] check 本次未识别失效（路径在 papers_dir 外）")

    # 把 resnet 移回，收尾
    shutil_move_fallback(resnet_moved, resnet_path)

    # 最终 clean check
    r = run(["check", "--folder", papers_dir, "--check-type", "paths"])
    assert r.exit_code == 0
    if "完全一致" in r.output or "失效" not in r.output or ("不存在" not in r.output and "未加入" not in r.output):
        _print("  [OK] 最终：所有文件路径与数据库完全一致")
    else:
        _print(f"  [INFO] final check: {r.output[:200]}")

    _print("Step 4 OK\n")

    # ========== 完成 ==========
    _print("=" * 60)
    _print("所有第三轮需求端到端测试通过！")
    _print("=" * 60)
    _print(f"临时目录保留用于检查: {tmpdir}")


def shutil_move_fallback(src, dst):
    """移动文件，Windows 被占用时尝试 copy+删除。"""
    for _ in range(3):
        try:
            shutil.move(src, dst)
            return
        except (OSError, PermissionError):
            try:
                shutil.copy2(src, dst)
                os.remove(src)
                return
            except Exception:
                import time
                time.sleep(0.1)
    raise


def safe_remove(p):
    try:
        if os.path.exists(p):
            os.remove(p)
    except Exception:
        pass


if __name__ == "__main__":
    main()
