from pathlib import Path
import os
from typing import Dict, Any, Union,List, Optional
import ujson
import jsonschema

from ..consts import BASE_DIR
from ..generators import GeneratorContext,LibraryGenerator

import click

# Load json file with Exeption
def load_json_file(file_path: Union[str, Path]) -> Dict[Any, Any]:
    """
    Load and parse JSON file with error handling
    """    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return ujson.load(f)
    except Exception as e:
        raise Exception(f"Error reading {file_path}: {e}")

# Save json file
def save_json_file(data: Dict[Any, Any], file_path: Union[str, Path], indent: int = 2):
    """
    Save data to JSON file with error handling
    """    
    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            ujson.dump(data, f, indent=indent, ensure_ascii=False)
    except Exception as e:
        raise Exception(f"Failed to save {file_path}: {e}")
    
def validate_json_schema(data: Dict[Any, Any], schema: Dict[Any, Any]) -> List[Dict[str, Any]]:
    """
    Validate data against JSON schema
    """
    validator = jsonschema.Draft7Validator(schema)

    errors = [
        {
            "path": " -> ".join(map(str, e.path)),
            "message": e.message,
            "value": str(e.instance)[:100]
        }
        for e in validator.iter_errors(data)
    ]

    if "default_version" in data and data.get("default_version"):
        version_names = [v["version_name"] for v in data.get("versions", [])]
        if data["default_version"] not in version_names:
            errors.append({
                "path": "default_version",
                "message": "No default version found in versions available",
                "value": data["default_version"]
            })

    return errors

def validate_config_file(config_file: Path, verbose: bool = True):
    """
    Validate & Get JSON config file against the schema.
    """
    schema = load_json_file(os.path.join(BASE_DIR,"resources/config_schema.json"))
    data = load_json_file(config_file)
    errors = validate_json_schema(data, schema)

    if errors and verbose:
        click.echo(f"{config_file}: {len(errors)} error(s)")
        for e in errors[:5]:
            click.echo(f"  • {e['message']} at {e['path']}")

    return data if not errors else None, errors

@click.command("generate", help="Generate API library from JSON configuration")
@click.argument(
    "config_files",
    nargs=-1,
    type=click.Path(exists=True, path_type=Path),
    metavar="[CONFIG_FILE|CONFIG_DIR]...",
)
@click.argument(
    "output_dir", type=click.Path(file_okay=False, writable=True, path_type=Path)
)
@click.option("--library-name", default="", help="Name of the generated library")
@click.option("-f","--force", is_flag=True)
def generate_command(config_files, output_dir, library_name,force):
    """
    validate, then generate codebase from config_files
    """
    
    if not config_files:
        raise click.ClickException("Please provide at least one JSON file to validate.")

    all_files = []
    for path in config_files:
        if path.is_dir():
            # Get all JSON files in the directory (non-recursive)
            all_files.extend(path.glob("*.json"))
        else:
            all_files.append(path)

    if not all_files:
        raise click.ClickException("No JSON files found to validate.")
    
    for file in all_files:
        # in case is forced
        if force:
            data = load_json_file(file)
        else:
            data, _ = validate_config_file(file)

        # Skip if data is unvalidated json & not Forced
        if data is None:
            continue

        api_name = data.get("api_name")

        click.echo(f"Starting library generation from {file}")
        click.echo(f"Output directory: {output_dir}")
        click.echo(f"Library name: {library_name}")
        click.echo(f"API: {api_name}")

        try:
            # Create GeneratorContext
            gen_context = GeneratorContext.create(
                config=data,
                output_dir=output_dir
            )

            # Instantiate LibraryGenerator
            lib_generator = LibraryGenerator()

            # Run the library generation
            result = lib_generator.generate_library(gen_context)

            click.echo(f"Successfully generated library '{result['library_name']}' "
                    f"with {result['total_files']} files in {result['output_dir']}")
        except Exception as e:
            click.echo(f"Error generating library: {str(e)}", err=True)
            raise click.ClickException(f"Failed to generate library: {str(e)}")

@click.command("validate", help="Validate JSON config files against the library schema")
@click.argument(
    "config_files",
    nargs=-1,
    type=click.Path(exists=True, path_type=Path),
    metavar="[CONFIG_FILE|CONFIG_DIR]...",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(writable=True, path_type=Path),
    help="Optional JSON file to save validation results",
)
@click.option("-q", "--quiet", is_flag=True)
def validate_command(config_files, output,quiet):
    """
    validate config files
    """
    if not config_files:
        raise click.ClickException("Please provide at least one JSON file to validate.")

    all_files = []
    for path in config_files:
        if path.is_dir():
            # Get all JSON files in the directory (non-recursive)
            all_files.extend(path.glob("*.json"))
        else:
            all_files.append(path)

    if not all_files:
        raise click.ClickException("No JSON files found to validate.")
    
    results=[]
    for file in all_files:
        data, errors = validate_config_file(file,verbose = not quiet)
        
        results.append({
            "file": str(file),
            "valid": data is not None,
            "errors": errors
        })

    
    total_files = len(results)
    valid_files = sum(1 for r in results if r["valid"])
    invalid_files = total_files - valid_files

    click.secho("\nSummary:", fg="cyan")
    click.echo(f"Total files: {total_files}")
    click.echo(f"Valid files: {valid_files}")
    click.echo(f"Invalid files: {invalid_files}")
    click.echo(f"Success rate: {(valid_files / total_files * 100) if total_files > 0 else 0:.2f}%")

    # Save to output file if requested
    if output:
        save_json_file(
            {
                "results": results,
                "summary": {
                    "total_files": total_files,
                    "valid_files": valid_files,
                    "invalid_files": invalid_files,
                    "success_rate": (valid_files / total_files * 100) if total_files > 0 else 0
                }
            }
        , output)
        click.secho(f"\nResults saved to {output}", fg="blue")
