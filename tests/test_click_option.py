import click
from click.testing import CliRunner

@click.command()
@click.argument('file_path')
@click.option('--add', 'add_tags_list', multiple=True)
def test_cmd(file_path, add_tags_list):
    click.echo(f'file_path: {file_path}')
    click.echo(f'add_tags_list: {add_tags_list}')
    click.echo(f'type: {type(add_tags_list)}')

runner = CliRunner()
result = runner.invoke(test_cmd, ['--add', 'tag1', '--add', 'tag2', 'myfile.pdf'])
print("Output:")
print(result.output)
print("Exit code:", result.exit_code)
if result.exception:
    import traceback
    traceback.print_exception(type(result.exception), result.exception, result.exception.__traceback__)
