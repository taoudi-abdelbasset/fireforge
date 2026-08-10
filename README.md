# FireForge

**A code generator that turns a JSON specification of a REST API into a ready-to-use Python client library.**

FireForge takes a declarative description of an API — base URL, versions, endpoints, authentication, retries, headers, request bodies — and generates typed Python client classes for it. The generated code depends on a small runtime shipped with this package, so the output stays thin and readable rather than duplicating HTTP plumbing in every project.

> **Distribution name:** this project is published on PyPI as `restapi-library`, but the import package and CLI are named `fireforge` and `forge-cli`.

---

## Table of contents

- [Why FireForge](#why-fireforge)
- [Installation](#installation)
- [Quick start](#quick-start)
- [How it works](#how-it-works)
- [CLI reference](#cli-reference)
- [Configuration reference](#configuration-reference)
  - [Top level](#top-level)
  - [Versions and endpoints](#versions-and-endpoints)
  - [Authentication](#authentication)
  - [Request bodies and file uploads](#request-bodies-and-file-uploads)
  - [Retry policy](#retry-policy)
  - [Header precedence](#header-precedence)
- [Environment variable interpolation](#environment-variable-interpolation)
- [Generated output](#generated-output)
- [Using a generated client](#using-a-generated-client)
- [Multi-user authentication](#multi-user-authentication)
- [Authentication hooks](#authentication-hooks)
- [Runtime API](#runtime-api)
- [Exceptions](#exceptions)
- [Requirements](#requirements)
- [Development](#development)
- [License](#license)

---

## Why FireForge

Integrating a third-party REST API usually means writing the same layers by hand for every service: a session wrapper, a token manager, retry logic, header merging, multipart handling, and a method per endpoint. That code is repetitive, easy to get subtly wrong, and hard to keep in sync when the API changes.

FireForge moves that description into a single JSON file:

- **One source of truth.** Endpoints, auth, timeouts, and retries live in a config file that can be reviewed and versioned like any other artifact.
- **Consistent clients.** Every generated client behaves the same way, so error handling and authentication are uniform across services.
- **Regeneration over patching.** When the upstream API changes, update the config and regenerate; the generated files are marked `DO NOT EDIT`.
- **Environment-aware.** Base URLs, credentials, and header values can be injected from environment variables, so the same config works across development, staging, and production.
- **No mandatory server spec.** FireForge does not require an OpenAPI document. It works from a compact configuration you write yourself, which is useful for APIs that publish no machine-readable spec.

---

## Installation

Install the runtime only — enough to *use* a generated client:

```bash
pip install restapi-library
```

Install with the generator CLI — needed to *produce* a client:

```bash
pip install "restapi-library[cli]"
```

Requires Python 3.11 or newer.

A typical deployment installs the base package in the application that consumes the API, and the `[cli]` extra only in the environment where clients are generated.

---

## Quick start

### 1. Describe the API

Save the following as `dummyjson.json`. It targets the public `dummyjson.com` test API and exercises anonymous calls, token login, and a JSON request body.

```json
{
  "api_name": "dummyjson",
  "base_url": "${DUMMYJSON_BASE_URL:https://dummyjson.com}",
  "default_version": "v1",
  "timeout": 30,
  "raise_on_error": true,
  "default_headers": {
    "Accept": "application/json"
  },
  "retry": {
    "attempts": 3,
    "delay": 1.0,
    "backoff_factor": 2.0,
    "jitter": true
  },
  "auth": {
    "type": "login_token",
    "login_endpoint": {
      "path": "/auth/login",
      "method": "POST",
      "login_body": {
        "username": "${DUMMYJSON_USERNAME:emilys}",
        "password": "${DUMMYJSON_PASSWORD:emilyspass}"
      },
      "token_field": "accessToken",
      "refresh_token_field": "refreshToken",
      "expires_in_field": "expiresIn",
      "timeout": 30
    },
    "token_placement": {
      "type": "header",
      "token_field_name": "Authorization",
      "prefix": "Bearer"
    }
  },
  "versions": [
    {
      "version_name": "v1",
      "endpoints": [
        {
          "function_name": "get_current_user",
          "path": "/auth/me",
          "method": "GET",
          "auth_required": true
        },
        {
          "function_name": "get_user",
          "path": "/users/{user_id}",
          "method": "GET",
          "auth_required": false
        },
        {
          "function_name": "add_product",
          "path": "/products/add",
          "method": "POST",
          "auth_required": true,
          "body_required": true,
          "request_body": { "type": "json" }
        }
      ]
    }
  ]
}
```

### 2. Validate it

```bash
forge-cli validate dummyjson.json
```

```
Summary:
Total files: 1
Valid files: 1
Invalid files: 0
Success rate: 100.00%
```

### 3. Generate the client

```bash
forge-cli generate dummyjson.json ./build --library-name dummyjson_client
```

### 4. Use it

```python
from dummyjson_client.dummyjson.versions.v1 import DummyjsonV1Client

# Anonymous endpoint - no login needed
user = DummyjsonV1Client.get_user(user_id=1)
print(user["firstName"])

# Authenticated endpoint - log in once, then call
DummyjsonV1Client.auth_handler.login()
me = DummyjsonV1Client.get_current_user()
print(me["email"])
```

All endpoint methods are class methods. There is no client instance to construct and no session object to pass around.

---

## How it works

```
config.json  ->  schema validation  ->  Jinja2 templates  ->  generated package
                                                                     |
                                                                     v
                                                          fireforge.core runtime
                                                     (auth, retries, bodies, HTTP)
```

1. **Validation.** The config is checked against a JSON Schema (Draft 7 validation of a 2020-12 schema document) bundled at `fireforge/resources/config_schema.json`. Cross-field rules are also enforced, such as `default_version` having to name a version that actually exists.
2. **Generation.** A `GeneratorContext` is built from the config and passed to the generators. `ClientsGenerator` renders one base client, one client class per API version, and the package `__init__` files.
3. **Runtime.** Generated classes subclass `StaticBaseApiClient` and declare endpoints with the `@endpoint` decorator. The decorator resolves path parameters, applies retry policy, and delegates to the runtime, which merges headers, serializes the body, applies authentication, and parses the response.

---

## CLI reference

The CLI entry point is `forge-cli`, installed with the `[cli]` extra.

### `forge-cli validate`

```
forge-cli validate [CONFIG_FILE|CONFIG_DIR]... [OPTIONS]
```

Validates one or more configuration files against the schema. Directory arguments are expanded to the `*.json` files directly inside them (non-recursive).

| Option | Description |
| --- | --- |
| `-o, --output PATH` | Write the full validation report, including per-file errors and a summary, to a JSON file. |
| `-q, --quiet` | Suppress per-file error listings; print only the summary. |

Up to five errors are printed per file, each with the failing JSON path and the offending value.

### `forge-cli generate`

```
forge-cli generate [CONFIG_FILE|CONFIG_DIR]... OUTPUT_DIR [OPTIONS]
```

Validates each config and generates a client library from it. The **last positional argument is the output directory**; every preceding argument is treated as an input config or a directory of configs. Files that fail validation are skipped rather than aborting the whole run.

| Option | Description |
| --- | --- |
| `--library-name TEXT` | Name of the generated top-level package directory. Defaults to `Fireforge-Lib`. |
| `-f, --force` | Skip schema validation and generate from the config as-is. |

> **Choose an importable `--library-name`.** The default, `Fireforge-Lib`, contains a hyphen and therefore cannot be imported as a Python package. Pass a valid Python identifier such as `dummyjson_client` for any library you intend to import directly.

### `forge-cli --version`

Prints the generator version.

---

## Configuration reference

### Top level

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `api_name` | string | yes | — | Identifier for the API. Matches `^[a-zA-Z0-9_-]+$` and becomes the generated package directory and class-name prefix. |
| `base_url` | string | yes | — | Root URL for all requests. Either a literal `http(s)://` URL or an interpolation of the form `${VAR:default}`. |
| `versions` | array | yes | — | One or more API versions. Must contain at least one entry. |
| `default_version` | string | no | — | Name of the default version. Must match one of the declared `version_name` values. |
| `default_headers` | object | no | — | Headers applied to every request. Values support environment interpolation. |
| `timeout` | integer | no | `30` | Default request timeout in seconds. Minimum `1`. |
| `raise_on_error` | boolean | no | `true` | Raise `APIError` on non-2xx responses instead of returning the parsed payload. |
| `retry` | object | no | — | Default retry policy. See [Retry policy](#retry-policy). |
| `auth` | object or null | no | `null` | Authentication configuration. See [Authentication](#authentication). |

Unknown top-level fields are rejected by the schema.

### Versions and endpoints

Each entry in `versions` declares a version name and its endpoints:

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `version_name` | string | yes | Matches `^[a-zA-Z0-9_-]+$`. Becomes the generated module name and part of the client class name. |
| `endpoints` | array | yes | At least one endpoint definition. |

Each endpoint supports:

| Field | Type | Required | Default | Description |
| --- | --- | --- | --- | --- |
| `function_name` | string | yes | — | Name of the generated method. Converted to `snake_case`. |
| `path` | string | yes | — | Path appended to `base_url`. Supports `{param}` placeholders, which become required keyword arguments on the generated method. |
| `method` | string | yes | — | One of `GET`, `POST`, `PUT`, `DELETE`, `PATCH`. |
| `auth_required` | boolean | no | `true` | Whether the configured auth handler is applied to this call. |
| `body_required` | boolean | no | `false` | Raise `ValueError` before sending if no body is supplied. |
| `params_schema` | object | no | — | JSON Schema describing the query parameters. |
| `raise_on_error` | boolean | no | `true` | Per-endpoint override of the global setting. |
| `timeout` | integer | no | — | Per-endpoint timeout in seconds; overrides the global timeout. |
| `retry` | object | no | — | Per-endpoint retry policy; overrides the global policy. |
| `headers` | object | no | — | Endpoint-specific headers, merged over the global defaults. |
| `override_default_headers` | boolean | no | `false` | Ignore `default_headers` entirely and send only the endpoint headers. |
| `request_body` | object | no | — | Body type and field definitions. See below. |

### Authentication

`auth.type` selects the scheme: `static_token` for a fixed key, or `login_token` for a credential exchange. `token_placement` is required in both cases. Setting `auth` to `null`, or omitting it, generates a client with no authentication handler.

#### Static token

For APIs authenticated with a fixed key:

```json
{
  "auth": {
    "type": "static_token",
    "access_key": "${SERVICE_API_KEY}",
    "token_placement": {
      "type": "header",
      "token_field_name": "X-API-Key"
    }
  }
}
```

`access_key` is required. Placeholder values such as `your_token_here`, `default_token`, or an empty string are rejected at import time with an `AuthenticationError`.

#### Login token

For APIs that exchange credentials for a bearer token:

```json
{
  "auth": {
    "type": "login_token",
    "login_endpoint": {
      "path": "/auth/login",
      "method": "POST",
      "login_body": {
        "username": "${API_USERNAME}",
        "password": "${API_PASSWORD}"
      },
      "token_field": "accessToken",
      "refresh_token_field": "refreshToken",
      "expires_in_field": "expiresIn",
      "timeout": 30
    },
    "token_placement": {
      "type": "header",
      "token_field_name": "Authorization",
      "prefix": "Bearer"
    }
  }
}
```

| Field | Required | Description |
| --- | --- | --- |
| `login_endpoint.path` | yes | Login path, relative to `base_url`. |
| `login_endpoint.method` | yes | HTTP method for the login call. |
| `login_endpoint.login_body` | no | Default credential payload. Values normally come from environment variables. Empty values are stripped before sending. |
| `login_endpoint.token_field` | yes | Field in the login response holding the access token. |
| `login_endpoint.refresh_token_field` | no | Field holding the refresh token. |
| `login_endpoint.expires_in_field` | no | Field holding the lifetime in seconds. Used to compute expiry, with a 60-second safety margin. |
| `login_endpoint.timeout` | no | Timeout for the login request, in seconds. Defaults to `30`. |
| `multi_user` | no | Keep one token per key instead of one per class. See [Multi-user authentication](#multi-user-authentication). |
| `multi_user_fallback` | no | In multi-user mode, permit calls without a key by falling back to the class-level token. |
| `refresh_endpoint` | no | Refresh path, method, and `body_schema`. |

#### Token placement

`token_placement` controls where the credential is attached:

| Field | Required | Description |
| --- | --- | --- |
| `type` | no | `header` (default), `query`, or `body`. |
| `token_field_name` | yes | Header name, query parameter name, or JSON body key. |
| `prefix` | no | String prefixed to the token, separated by a space. Typically `Bearer`. Header placement only. |

Login is explicit: the runtime never logs in automatically. Call `login()` before the first authenticated request. If the token is missing or expired, an `AuthenticationError` is raised rather than silently re-authenticating.

### Request bodies and file uploads

`request_body.type` selects the serialization strategy:

| Type | Behaviour |
| --- | --- |
| `json` | Sends the body as a JSON payload. This is the default. |
| `form_data` | Sends `multipart/form-data`. Requires `fields`. Supports file uploads. |
| `urlencoded` | Sends `application/x-www-form-urlencoded`. Requires `fields`. |
| `raw` | Sends the body verbatim. Requires `content_type` — for example `text/xml` or `text/csv`. |
| `none` | Sends no body. |

For `form_data` and `urlencoded`, each entry in `fields` describes one field:

| Field | Applies to | Description |
| --- | --- | --- |
| `field_type` | all | `text` (default) or `file`. |
| `required` | all | Raise `ValueError` if the field is missing. Defaults to `false`. |
| `content_type` | all | Explicit content type. For text fields, a value of `application/json` serializes a dict argument to JSON. |
| `description` | all | Human-readable documentation for the field. |
| `multiple` | file only | Accept a list of files for this field. |
| `allowed_extensions` | file only | Whitelist such as `[".pdf", ".png"]`. Rejects anything else. |
| `max_file_size` | file only | Maximum size per file, in bytes. |
| `max_total_size` | body level | Maximum combined size for all files, in bytes. |

Example:

```json
{
  "function_name": "upload_invoice",
  "path": "/documents/invoices",
  "method": "POST",
  "auth_required": true,
  "request_body": {
    "type": "form_data",
    "fields": {
      "reference": { "field_type": "text", "required": true },
      "metadata":  { "field_type": "text", "content_type": "application/json" },
      "document":  {
        "field_type": "file",
        "required": true,
        "allowed_extensions": [".pdf"],
        "max_file_size": 5242880
      }
    }
  }
}
```

```python
InvoiceV1Client.upload_invoice(
    body={"reference": "INV-2044", "metadata": {"source": "erp"}},
    files={"document": "/path/to/invoice.pdf"},
)
```

File fields accept a filesystem path, an open file object, raw `bytes`, or an explicit `(filename, fileobj, content_type)` tuple. Paths are opened by the runtime and closed after the request completes, including on failure. Content types are inferred from the extension for `.pdf`, `.jpg`, `.jpeg`, `.png`, `.txt`, and `.json`, and fall back to `application/octet-stream`.

### Retry policy

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `attempts` | integer | `3` | Total attempts, including the first. Minimum `1`. |
| `delay` | number | `1.0` | Seconds to wait before the first retry. |
| `backoff_factor` | number | `2.0` | Multiplier applied to the delay after each failed attempt. |
| `jitter` | boolean | `true` | Randomize the delay to avoid synchronized retries. |

Retries apply only to failures worth repeating: HTTP `429`, `500`, `502`, `503`, `504`, and connection or timeout errors. Other exceptions propagate immediately. When every attempt fails, `RetryExhaustedError` is raised with the last underlying error attached.

### Header precedence

Headers are merged in three layers, each overriding the previous one:

1. `default_headers` from the top level of the config — skipped when the endpoint sets `override_default_headers: true`.
2. `headers` declared on the endpoint.
3. `headers` passed at call time.

Authentication headers are applied after this merge.

---

## Environment variable interpolation

Any string value in the configuration may reference the environment:

| Syntax | Behaviour |
| --- | --- |
| `${VAR}` | Substitutes the value of `VAR`, or an empty string when unset. |
| `${VAR:default}` | Substitutes the value of `VAR`, or `default` when unset. |

Interpolation applies recursively through nested objects and arrays, so it works for base URLs, credentials, and header values alike.

Two constraints are worth remembering:

- **`base_url` must supply a default.** The schema accepts either a literal URL or the `${VAR:default}` form for this field; a bare `${VAR}` fails validation.
- **Values are resolved at import time.** Configuration is parsed when the generated client class is defined. Set environment variables — or load your `.env` file — before importing the client module.

---

## Generated output

```
<output_dir>/
└── <library-name>/
    └── <api_name>/
        ├── __init__.py         # re-exports the base client and every version client
        ├── base.py             # auth handler + base client with shared configuration
        └── versions/
            ├── __init__.py     # re-exports the version clients
            └── <version>.py    # one class per API version, one method per endpoint
```

Class names are derived from the configuration in `PascalCase`:

| Artifact | Pattern | Example |
| --- | --- | --- |
| Base client | `{ApiName}ApiBaseClient` | `DummyjsonApiBaseClient` |
| Version client | `{ApiName}{VersionName}Client` | `DummyjsonV1Client` |
| Auth handler | `{ApiName}{AuthType}Auth` | `DummyjsonLoginTokenAuth` |

Every generated file carries a `THIS FILE IS GENERATED — DO NOT EDIT` header and a generation timestamp. Regenerate rather than editing; local changes are overwritten on the next run.

The `<library-name>` directory contains no `__init__.py` and therefore behaves as an implicit namespace package. Place `<output_dir>` on the import path and import the full dotted path, as shown below.

---

## Using a generated client

```python
from dummyjson_client.dummyjson.versions.v1 import DummyjsonV1Client
```

### Anonymous calls

```python
user = DummyjsonV1Client.get_user(user_id=1)
```

Path placeholders become required keyword arguments. Omitting one raises `ValueError` listing the missing parameters before any request is sent.

### Authenticated calls

```python
DummyjsonV1Client.auth_handler.login()
me = DummyjsonV1Client.get_current_user()
```

### Bodies, query parameters, and per-call overrides

```python
created = DummyjsonV1Client.add_product(
    body={"title": "Standing desk", "price": 420},
    params={"validate": "true"},
    headers={"X-Request-Id": "b3f1c2"},
)
```

Every generated method accepts `body`, `params`, `headers`, and `**kwargs`; methods for `form_data` endpoints also accept `files`, and methods on authenticated endpoints accept `instant_key`.

### Responses

Responses are parsed as JSON when possible and returned as a `dict` or `list`. Plain text is returned as a string, and an empty body returns `None`. For dict responses the runtime attaches `_status_code`, plus `_error: True` when the status is 400 or above.

When `raise_on_error` is `true`, non-2xx responses raise `APIError`. When it is `false`, the parsed payload is returned so the caller can inspect the status directly.

---

## Multi-user authentication

By default a login token is stored on the client class and shared by the whole process. That is the right model for a service authenticating as itself, but not for an application acting on behalf of many end users.

Set `multi_user: true` on the auth configuration to keep a separate token per key:

```json
{
  "auth": {
    "type": "login_token",
    "multi_user": true,
    "login_endpoint": { "...": "..." },
    "token_placement": { "...": "..." }
  }
}
```

```python
auth = ClinicV2Client.auth_handler

# One login per user, each stored under its own key
auth.login(credentials={"username": "dr.hassan", "password": "..."}, key="user-42")
auth.login(credentials={"username": "dr.samira", "password": "..."}, key="user-77")

# Select the identity per call
record = ClinicV2Client.get_patient(patient_id="P-1001", instant_key="user-42")

# Release one user's token
auth.logout(key="user-42")
```

In multi-user mode, `login()` requires a `key`, and authenticated calls require `instant_key`. Calling without one raises `AuthenticationError` unless `multi_user_fallback: true` is set, in which case the runtime falls back to the class-level token.

Token state is held in memory, per process. Multi-worker deployments authenticate independently in each worker.

---

## Authentication hooks

Login handlers expose three override points. Subclass the generated auth handler when an API needs signed headers, a non-standard response shape, or custom error mapping:

| Hook | When it runs | Purpose |
| --- | --- | --- |
| `on_before_login(request_kwargs)` | Before the login request is sent | Inspect or extend `url`, `method`, `json`, `headers`, `params`. The returned dict is merged over the defaults; existing keys cannot be removed. |
| `on_after_login(response_data)` | After a successful login | Read extra fields from the response. Raising `AuthenticationError` aborts the login. |
| `on_login_error(status_code, response_data)` | After a non-2xx login response | Map upstream error codes to your own messages. Raising replaces the default error; returning normally lets the default path continue. |

```python
from dummyjson_client.dummyjson.base import DummyjsonLoginTokenAuth

class SignedAuth(DummyjsonLoginTokenAuth):

    @classmethod
    def on_before_login(cls, request_kwargs):
        request_kwargs["headers"]["X-Signature"] = sign(request_kwargs["json"])
        return request_kwargs

    @classmethod
    def on_login_error(cls, status_code, response_data):
        if status_code == 423:
            raise AuthenticationError("Account locked. Contact support.")
```

Set `debug = True` on a login handler to print the full login request and response. Use it for diagnosis only — it prints credentials and tokens.

---

## Runtime API

`fireforge.core` is the public runtime imported by generated code.

| Object | Description |
| --- | --- |
| `StaticBaseApiClient` | Base class for generated clients. Holds `api_name`, `api_config`, `version`, and `auth_handler`, and implements `execute_request`. |
| `endpoint(method, path, ...)` | Decorator that turns a method stub into a class method performing an HTTP call. Handles path resolution, body requirements, and retries. |
| `BaseAuth` | Abstract auth handler. Subclasses register themselves under an `auth_type` in `BaseAuth._registry`. |
| `StaticTokenAuth` | Fixed-token handler, registered as `static_token`. |
| `LoginTokenAuth` | Login-based handler, registered as `login_token`. Provides `login`, `logout`, `is_token_expired`, `has_token`, and the hooks above. |

`fireforge.functions` additionally exposes `to_snake_case` and `to_pascal_case`, the naming helpers used by the templates.

Custom auth schemes can be added by subclassing `BaseAuth` with a new `auth_type`; the registry then makes the type available to generated base clients.

---

## Exceptions

All exceptions derive from `APILibraryError`, so a single `except` clause can cover the library:

| Exception | Raised when |
| --- | --- |
| `APILibraryError` | Base class for everything below. |
| `APIError` | The API returned an error response, or the request failed while `raise_on_error` was enabled. Carries `status_code`. |
| `AuthenticationError` | Credentials are missing, invalid, expired, or the login call failed. |
| `ValidationError` | Input validation failed. |
| `RetryExhaustedError` | Every retry attempt failed. The message includes the last underlying error. |
| `ConfigurationError` | The client configuration is invalid or incomplete. |

```python
from fireforge.exceptions import APIError, AuthenticationError, RetryExhaustedError

try:
    data = DummyjsonV1Client.get_current_user()
except AuthenticationError:
    DummyjsonV1Client.auth_handler.login()
    data = DummyjsonV1Client.get_current_user()
except RetryExhaustedError as exc:
    logger.error("Upstream unavailable: %s", exc)
except APIError as exc:
    logger.error("API error %s: %s", exc.status_code, exc)
```

---

## Requirements

| Component | Requirement |
| --- | --- |
| Python | 3.11 or newer |
| Runtime dependencies | `requests`, `jsonschema` |
| CLI extra (`[cli]`) | `jinja2`, `click`, `ujson` |

The generated code depends only on the runtime, so applications consuming a client do not need the generator installed.

---

## Development

```bash
git clone <repository-url>
cd FireForge
poetry install
```

Common tasks:

```bash
# Formatting and linting
poetry run black .
poetry run isort .
poetry run pylint fireforge

# Install the git hooks
poetry run pre-commit install
```

Commit messages follow the Conventional Commits specification and are checked by `gitlint`. Releases are versioned by `python-semantic-release`, driven by the commit history.

---

## License

Released under the MIT License. See [LICENSE](LICENSE) for the full text.
