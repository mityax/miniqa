import os
import re
import subprocess
from typing import Any, Mapping

from ruamel.yaml import YAML

from miniqa.lib import assets_server

BUILTIN_ENV_VARS = {
    'ASSETS_SERVER_ADDR': f'http://10.0.2.2:{assets_server.PORT}'
}


yaml = None

def load_yaml(
    yaml_text: str,
    fn: str,
    extra_env: dict[str, Any] = None,
    allow_env_from_key: str | None = None,
    ignore_missing_vars: bool = False,
    allow_extra_docs: bool = False,
) -> dict[str, Any]:
    global yaml
    yaml = yaml or YAML(typ='safe')

    if allow_extra_docs:
        data = next(yaml.load_all(yaml_text))
    else:
        data = yaml.load(yaml_text)

    if not isinstance(data, dict):
        return data

    env = {
        **BUILTIN_ENV_VARS,
        **os.environ,
        **(extra_env or {}),
    }

    if allow_env_from_key and allow_env_from_key in data:
        data[allow_env_from_key] = substitute_vars(data[allow_env_from_key], env)  # to support using vars in vars
        env.update(data[allow_env_from_key])

    data = substitute_vars(data, env, ignore_missing_vars=ignore_missing_vars)
    data = evaluate_inline_scripts(data)
    data = unescape(data)

    return data


VAR_PATTERNS = [
    re.compile(r"(?<!\$)\$(?P<name>\w+)"),                       # $ENV_VAR
    re.compile(r"(?<!\$)\$\{(?P<name>\w+)}"),                    # ${ENV_VAR}
    re.compile(r"(?<!\$)\$\{(?P<name>\w+):-(?P<default>.*?)}"),  # ${ENV_VAR:-default_value}
]

def substitute_vars(data: Any, vars: Mapping[str, str], ignore_missing_vars: bool = False):
    def _getvar(name, default):
        if not ignore_missing_vars and name not in vars and default is None:
            raise KeyError(f"Variable '{name}' does not exist and no default set.")
        return vars.get(name, default)

    if isinstance(data, str):
        for pattern in VAR_PATTERNS:
            # Check for full matches, return var value directly (allows typed variables in YAML):
            if (m := pattern.match(data.strip())) and len(m.group(0)) == len(data.strip()):
                return _getvar(m.group('name'), m.groupdict().get('default'))
            # Check for in-string matches:
            data = pattern.sub(
                lambda m: _getvar(m.group('name'), m.groupdict().get('default')),
                data,
            )
    elif isinstance(data, dict):
        data = {k: substitute_vars(v, vars) for k, v in data.items()}
    elif isinstance(data, list):
        data = [substitute_vars(item, vars) for item in data]
    return data


def evaluate_inline_scripts(data: dict[str, Any]) -> dict[str, Any]:
    if isinstance(data, str):
        # For `$(my-command my-arg)`, e.g. `$(ls -la)`:
        data = re.sub(
            r"(?<!\$)\$\((.*?)\)",
            lambda m: subprocess.getoutput(m.group(1)).strip(),
            data,
            re.DOTALL,
        )
    elif isinstance(data, dict):
        data = {k: evaluate_inline_scripts(v) for k, v in data.items()}
    elif isinstance(data, list):
        data = [evaluate_inline_scripts(item) for item in data]
    return data


def unescape(data: dict[str, Any]) -> dict[str, Any]:
    if isinstance(data, str):
        # Unescape "$$" into "$"
        data = data.replace("$$", "$")
    elif isinstance(data, dict):
        data = {k: unescape(v) for k, v in data.items()}
    elif isinstance(data, list):
        data = [unescape(item) for item in data]
    return data


