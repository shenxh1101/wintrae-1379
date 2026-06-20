import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import click

print("=== 测试 click multiple option 的最小案例 ===")

@click.command()
@click.argument("file_path")
@click.option("--add-tags", "tag_add_list", multiple=True)
@click.option("--topic")
def test_cmd(file_path, tag_add_list, topic):
    print(f"file_path = {file_path!r}")
    print(f"tag_add_list = {tag_add_list!r}, type={type(tag_add_list)}")
    print(f"topic = {topic!r}")
    print(f"在函数内，Python 中 list(tag_add_list) 会调用啥? list={list!r}")
    result = list(tag_add_list)
    print(f"list(tag_add_list) = {result!r}")

from click.testing import CliRunner
runner = CliRunner()
result = runner.invoke(test_cmd, [
    "--topic", "NLP",
    "--add-tags", "nlp",
    "--add-tags", "survey",
    "myfile.pdf",
])
print("Exit code:", result.exit_code)
print("Output:")
print(result.output)
if result.exception:
    import traceback
    traceback.print_exception(type(result.exception), result.exception, result.exception.__traceback__)
