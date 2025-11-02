from pathlib import Path
from typing import Dict, Any
from jinja2 import Environment, FileSystemLoader
from ..functions import to_pascal_case ,to_snake_case,_parts
import datetime

class GeneratorContext:
    def __init__(self, config: Dict[str, Any], api_name: str, output_dir: Path,lib_name: str = "FireForge-Library" ):
        self.config = config
        self.api_name = api_name
        self.output_dir = output_dir
        self.lib_name = lib_name

    @classmethod
    def create(cls, config: Dict[str, Any], output_dir: str,lib_name:str) -> 'GeneratorContext':
        return cls(
            config=config,
            lib_name=lib_name if lib_name else "Fireforge-Lib",
            api_name=config.get("api_name","api_name"),
            output_dir=Path(output_dir)
        )

class BaseGenerator:
    """Base class for all generators"""
    
    def __init__(self, context: GeneratorContext, template_dir: str):
        self.context = context
        self.jinja_env = Environment(
            loader=FileSystemLoader(template_dir),
            trim_blocks=True,
            lstrip_blocks=True
        )
        # Add filters
        self.jinja_env.filters['snake_case'] = to_snake_case
        self.jinja_env.filters['pascal_case'] = to_pascal_case
        self.jinja_env.globals['now'] = datetime.datetime.now
        self.jinja_env.filters['_parts'] = _parts
    
    def render_template(self, template_name: str, **kwargs) -> str:
        """Render template with context"""
        template = self.jinja_env.get_template(template_name)
        return template.render(
            api_name=self.context.api_name,
            config=self.context.config,
            **kwargs
        )
    
    def save_file(self, content: str, file_path: Path) -> Dict[str, Any]:
        """Save file and return info"""
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return {
            'file_path': str(file_path),
            'size': len(content.encode('utf-8')),
            'lines': content.count('\n') + 1
        }
