"""测试 tag 命令"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from click.testing import CliRunner
from papertool.cli import cli

runner = CliRunner()

db_path = "./test_db/papers.json"
log_dir = "./test_db/logs"
test_file = os.path.abspath("./tests/test_papers/old_paper.pdf")

print("测试 --status 选项:")
result = runner.invoke(cli, [
    "--db-path", db_path,
    "--log-dir", log_dir,
    "tag",
    "--status", "read",
    test_file,
])
print(result.output)
print("Exit code:", result.exit_code)
print()

print("测试 --add 选项:")
result = runner.invoke(cli, [
    "--db-path", db_path,
    "--log-dir", log_dir,
    "tag",
    "--add", "mytag",
    test_file,
])
print(result.output)
print("Exit code:", result.exit_code)
if result.exception:
    import traceback
    traceback.print_exception(type(result.exception), result.exception, result.exception.__traceback__)
