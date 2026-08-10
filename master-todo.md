# MASTER TODO

# Notes

## General Notes

- try to use the old `os.path.join` it more clear and backward compatible than
  `path_instance / string` or `path_instance \ path_instance`

- it is not required to create folder/module,
  for example: the exceptions module could be a single file ;
  and the opposite is for generators, you created a module (very good),
  but you put all the "Generators" - that are classes - in a single file ;
  it will be better to put each one in it own file, have a `base.py`
  for the `BaseGenerator` and `GenerationContext`
  
- for `GenerationContext` it better to name it `GeneratorContext`,
  Associate it with the name `Generator`, not with the verb `Generation`
- use `to_snake_case` and `to_pascal_case` from `functions.py`
  
- using python >=3.11 is better to use `match ... case` (base_model.py:58)
  
- and because, we will not handle request/response bodies at first and
  use only dict, we don't need the function above ;
  but when we will need to do that, we will use pydantic and not normal Dataclasses

- keep the 'tui/cli' prompt printed textonly, no emoji
- Change Schema to better froma "api_name" & "verison : []" instad of {{}..}
- Already have GeneratorContext class use it and put correct naming
- limit function layers
- use yeild???
- Not Load Json maney time & only use ujson instead of json

## base_client.py

```python
class StaticBaseApiClient(ABC):
    api_name: ClassVar[str] = "unknown_api" # we are an API client, `name` is a good name
    api_config: ClassVar[Dict[str, Any]] = {} # what is this, if it the "raw" configuration
    ...
    _parsed_config: ClassVar[Dict[str, Any]] = {} # why not _config, there is no _config attribute in the class.
    ...
        @classmethod
    def _get_parsed_config(cls) -> Dict[str, Any]:
        """Parse configuration from class api_config attribute (dynamic - no cache)"""
        if hasattr(cls, 'api_config') and isinstance(cls.api_config, dict):
            return EnvParser.parse_config(cls.api_config) # what is EnvParser, why does it parse manualy the config file, that is a json file ??
        return {}
    ...
    @classmethod
    def _get_base_url(cls, base_url: Optional[str] = None) -> str: # what is the role of the `base_url` arg
        """Resolve base URL from config or environment (dynamic)"""


        # == what is the role of the `base_url` arg, no need for this block
        if base_url:
            return base_url.rstrip('/')
        # == end block

        parsed_config = cls._parsed_config # usless instruction, no need to put it in a new variable
        config_url = parsed_config.get('base_url') # cls._parsed_config.get("base_url")

        if config_url:
            return str(config_url).rstrip('/')  # why rstrip, and not keep the base_url as `url/`

        return 'http://localhost' # raising an exception is more verbose here

    ...
```
