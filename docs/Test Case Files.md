
# miniQA – Test Case File Reference

miniQA tests are YAML files that are structured like the following (all fields are optional):

```yaml

from: <string>  # base snapshot name

env:            # list of variables
   <mapping of (str -> any)>

defs:           # custom steps
   <mapping of (str -> list of steps)>

assets:         # floating assets served via http
	<mapping of (str -> str)>

steps:          # the steps to run for this test
	<list of steps>
```


## Fields

### `from` – Loading a Base Snapshot

Via the `from` field, you can specify which snapshot your test starts from; if you omit this field, the test starts from a fresh VM boot.

```yaml
from: my_snapshot
```

### `env` – Creating Variables

The `env` field takes a mapping of variables, e.g.:

```yaml
env:
    USERNAME: "Jane Doe"
    BUTTON_POSITION: 15% 50%
    POPUP_REGION: 20% 25% 60% 50%
```

Variables can be of any YAML-supported type and can be used in any value in the test file that defines them, e.g.

```yaml
steps:
	- type_text: "${USERNAME}@example.com"
	- click: $BUTTON_POSITION
	- type_text: "${PASSWORD:-defaultpassword123}"  # fallback values are supported
	- wait:
		for: welcome_popup
		regions: $POPUP_REGION
```

You can also specify global variables in your `miniqa.yml` file's `env` field; these variables will be accessible across all tests and are therefore particularly useful for project-wide configurations.

### `defs` – Defining Reusable Custom Steps

A custom step is just a list of steps that get a name and can be reused multiple times using that name, e.g.:

```yaml
defs:
    switch_page:
        - click: 5% 95%  # "next page" button
        - wait:

steps:
    - wait:
        for: create_user_window
    - type_text: $FULL_NAME
    - switch_page:
    - type_text: $USERNAME
    - switch_page:
    - type_text: $PASSWORD
    - click:
        find:
            text: "Create User"
```

Note that it is advisable to keep custom steps short and bulletproof; this is because you'll have less debugging information in the webui (information about individual sub-steps results is not accessible in the webui). However, should you run into trouble, you can either run in verbose mode (`miniqa -vv editor`) to see logs on which exact step failed, or temporarily insert the substeps of your custom step directly into your tests steps.

### `assets` – Creating Floating Assets

"Floating assets" are assets that are served by miniQA's asset server only while the current test case are running; they're specified as raw text and their value will be served as-is:

```yaml
assets:
    some_script: |
        sleep 1s
        echo "some_script is done."

steps:
    - open_terminal:
    - type_text: "curl ${ASSETS_SERVER_ADDR}/some_script | sh"
```

As you can see above, miniQA provides a built-in `ASSETS_SERVER_ADDR` variable that always points to the running asset server.

Note that floating assets are intended for small text snippets such as brief scripts. This way, you can significantly reduce the risk of typos and increase transmission speed drastically when you need to input text into your VM.

You can also provide larger files or directories to your VM by specifying `serve_assets` in your `miniqa.yml`

<!-- TODO: insert link --->

### `steps` – Writing Your Actual Tests

The `steps` list is the heart of all test cases; it's the script miniQA executes when running your tests, as you can see in the several examples above.

A detailed reference of all built-in steps and their usage is available [here](Steps.md).





