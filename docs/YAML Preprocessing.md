# miniQA – YAML Preprocessing

YAML files are preprocessed right after they're parsed. This means that

- preprocessing only ever happens once per file load, and will, for example, not be repeated when repeatedly running a custom step.
- variables cannot be changed at runtime

## Variables

You can reference environment variables passed to miniQA as well as those defined in the `env` fields of your test cases or `miniqa.yml` files using these well-known syntaxes:

```yaml
$MY_VARIABLE
```
```yaml
${MY_VARIALBE}
```
```yaml
${MY_VARIABLE:-my default value}
```

Variables can be part of a string in which they'll be substituted (e.g. `"My name is $MY_NAME, nice to meet you!"`), or they can be directly used as value in YAML:

```yaml
my_key: $MY_VALUE

my_list:
    - $MY_LIST_ITEM
```

If you use variables directly as values, and not as part of a string substitution, their original value type will be preserved; therefore you can also store complex structures like lists or mappings in variables.

## Inline Scripts

miniQA allows you to include short inline shell scripts in your YAML files, using the `$(my-command my-arg)` syntax:

```yaml
my_key: "Current directory: $(pwd), system info: $(uname -a)"
```

Scripts are ran in the directory your `miniqa.yml` file is located in.

## Escaping

Both, the variable and the inline script syntax can be escaped using a double `$` sign – e.g.:

```yaml
$$NOT A VARIABLE  # becomes: "$NOT A VARIABLE"
$$(not a script)  # becomes: "$(not a script)"
```

There's no need to escape `$` signs generally; since variable parsing is regex-based, any dollar sign that is not part of a valid variable or inline script structure will be left as-is.
