"""创建测试用的 PDF 文件和测试 CLI 全流程
"""
import os
import sys
import tempfile
import subprocess

def create_minimal_pdf(filepath, title=None, author=None):
    """创建一个最小的有效 PDF 文件"""
    content = [
        b"%PDF-1.4\n",
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>\nendobj\n",
        b"xref\n0 4\n0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n",
        b"trailer\n<< /Size 4 /Root 1 0 R >>\n",
        b"startxref\n190\n%%EOF\n",
    ]
    
    with open(filepath, "wb") as f:
        f.write(b"".join(content))


def main():
    test_dir = os.path.join(os.path.dirname(__file__), "test_papers")
    os.makedirs(test_dir, exist_ok=True)
    
    papers = [
        ("2023 - Smith et al - Deep Learning for NLP.pdf", "Deep Learning for NLP", "John Smith"),
        ("random_paper_2022.pdf", "Machine Learning Survey", "Alice Wang"),
        ("old_paper.pdf", None, None),
    ]
    
    for fname, title, author in papers:
        fpath = os.path.join(test_dir, fname)
        create_minimal_pdf(fpath)
        print(f"Created: {fname}")
    
    print(f"\n测试文件已创建在: {test_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
