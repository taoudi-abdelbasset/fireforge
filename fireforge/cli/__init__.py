import click
from fireforge.consts import BASE_DIR

from ._commands import generate_command, validate_command

__version__ = "0.0.0"


@click.group()
@click.version_option(__version__, prog_name="API Library Generator")
def cli():
    """FireForge

    Two commands:
    - validate: Check if config files are valid or not
    - generate: Create API library from config (validates first unless --force)
    """


def run():
    cli.add_command(validate_command)
    cli.add_command(generate_command)

    cli()
