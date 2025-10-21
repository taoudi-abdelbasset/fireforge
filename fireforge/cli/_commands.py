from pathlib import Path

import click


@click.command("generate", help="Generate API library from JSON configuration")
@click.argument(
    "config_files",
    nargs=-1,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.argument(
    "output_dir", type=click.Path(file_okay=False, writable=True, path_type=Path)
)
@click.option("--library-name", default="", help="Name of the generated library")
def generate_command(config_files, output_dir, library_name):
    """
    validate, then generate codebase from config_files
    """
    raise NotImplementedError


@click.command("validate", help="Validate JSON config files against the library schema")
@click.argument(
    "config_files",
    nargs=-1,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
)
@click.option(
    "-o",
    "--output",
    type=click.Path(dir_okay=False, writable=True, path_type=Path),
    help="Optional JSON file to save validation results",
)
def validate_command(config_files, output):
    """
    validate config files
    """
    raise NotImplementedError
