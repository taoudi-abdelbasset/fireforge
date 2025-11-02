import re
import os
from typing import List
from ..functions import to_pascal_case ,to_snake_case,_parts
from ..consts import URL_PATH_PARAM_PATTERN,BASE_DIR

from .base import GeneratorContext,BaseGenerator

class ClientsGenerator(BaseGenerator):
    """Generate API client classes"""

    def __init__(self, context: GeneratorContext):
        template_dir = os.path.join(BASE_DIR, "resources", "templates")
        super().__init__(context, template_dir)
    
    def generate(self):
        """Generate API client files including base client and version-specific clients."""
        core_dir = os.path.join(self.context.output_dir, self.context.lib_name ,self.context.api_name)
        
        base_client_class_name = f"{to_pascal_case(self.context.api_name)}ApiBaseClient"

        base_content = self.render_template(
            "base_client.py.j2",
            base_client_class_name=base_client_class_name
        )

        client_base_file = os.path.join(core_dir, "base.py")
        yield self.save_file(base_content, client_base_file)
        
        # Generate version clients
        client_versions_dir = os.path.join(core_dir,"versions")
        client_classes = []

        
        # TODO: Add logique for handeling default version
        # loop each version
        for version_config in self.context.config.get("versions", []):
            client_version_class_name = f"{to_pascal_case(self.context.api_name)}{to_pascal_case(version_config.get("version_name"))}Client"
            client_classes.append((version_config.get("version_name"), client_version_class_name))

            content = self.render_template(
                "client_version.py.j2",
                base_client_class_name=base_client_class_name,
                version_config = version_config,
                # get path params map {"endpoint"->["param_k", ...]}
                path_params = {
                    endpoint.get("function_name"): self._extract_path_params(endpoint.get("path")) for endpoint in version_config.get("endpoints")
                },
                client_class_name=client_version_class_name
            )

            client_version_file = os.path.join(client_versions_dir, f"{version_config.get("version_name")}.py")

            yield self.save_file(content, client_version_file)
        
        # Generate versions __init__.py
        versions_init = self._gen_versions_init(client_classes)
        versions_init_file = os.path.join(client_versions_dir ,"__init__.py")
        yield self.save_file(versions_init, versions_init_file)

        # Generate base __init__.py
        base_init = self._gen_api_init(client_classes,base_client_class_name)
        base_init_file = os.path.join(core_dir ,"__init__.py")
        yield self.save_file(base_init, base_init_file)
    
    def _gen_versions_init(self, client_classes: List[tuple]) -> str:
        """Create __init__.py for versions"""
        imports = []
        class_names = []
        
        for version_name, class_name in client_classes:
            imports.append(f"from .{version_name} import {class_name}")
            class_names.append(class_name)
        
        imports_str = "\n".join(imports)
        exports = ", ".join(f'"{name}"' for name in class_names)
        
        return f'''"""
API version clients for {self.context.api_name}
"""
{imports_str}

__all__ = [{exports}]
'''
    
    def _gen_api_init(self, client_classes: List[tuple],base_client_class_name:str):
        """Create main API __init__.py"""
        imports = []
        class_names = []
        
        for version_name, class_name in client_classes:
            imports.append(f"from .versions.{version_name} import {class_name}")
            class_names.append(class_name)
            
        if base_client_class_name:
            imports.append(f"from .base import {base_client_class_name}")
            class_names.append(base_client_class_name)
        
        imports_str = "\n".join(imports)
        exports = ", ".join(f'"{name}"' for name in class_names)
        
        return f'''"""
Generated API client for {base_client_class_name}
"""
{imports_str}

__all__ = [{exports}]
'''

    def _extract_path_params(self, path: str) -> list[str]:
        if not path:
            return []
        return re.findall(URL_PATH_PARAM_PATTERN, path)
    
class LibraryGenerator:
    """Main generator that creates the complete library"""
    def generate_library(
        self, 
        context: GeneratorContext
    ):
        """Generate complete library RestAPI"""
        
        # Available generators        
        available_generators = {
            "clients": ClientsGenerator
        }
        # Generate code
        results = {
            'api_name': context.api_name,
            'library_name': context.lib_name,
            'output_dir': str(context.output_dir),
            'generators': {},
            'total_files': 0
        }
        for gen_name in available_generators:
            # Giving context to each generator
            generator = available_generators[gen_name](context)
            generated_files = list(generator.generate())
            results['generators'][gen_name] = {
                'files': generated_files 
            }
            results['total_files'] += len(generated_files)  # Update total file count
        return results