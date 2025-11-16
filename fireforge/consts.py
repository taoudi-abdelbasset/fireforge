from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
URL_PATH_PARAM_PATTERN = r"\{([^}]+)\}"
DOTENV_PLACEHOLDER_PATTERN = r'\${([^}]+?)(?::([^}]*))?}'
