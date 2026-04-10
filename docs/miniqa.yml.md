
# miniQA – miniqa.yml File Reference

The `miniqa.yml` file contains the main configuration of your test suite.

```yaml
image: <string>              # image to boot

tests_directory: <string>    # optional, default: ./tests

refs_directory: <string>     # optional, default: ./refs

out_directory: <string>      # optional, default: ./out

cache_directory: <string>    # optional, default is a temporary directory

headless: <bool>             # optional, default: true

qemu_args:                   # optional
    <list of string>

use_ovmf:                    # optional
    <bool>|<OVMFConfig>

serve_assets:                # optional
    <list of string>

env:                         # optional; global variables
    <mapping of (str -> any)>

ignore_regions:              # optional
    <Region>|<list of Region>
```


## Fields

### `image` – The OS Image to Load

Path to an image file to load, can be of any QEMU-supported type (e.g. a raw `.img` or a `.qcow2`).

### `tests_directory` – Path to Test Case Files

Path to your test case files.

### `refs_directory` – Path to Reference Screenshots

Path to your reference screenshots.

### `out_directory` – Screenshot Output Path [deprecated]

This is where the `screenshot` step will place its screenshots if a reference screenshot already exists for the name.

> **Deprecated** – This will be removed or substantially changed in the future; it's best to avoid relying on any out-folder-specific behaviors for now.

### `cache_directory` – Cache folder

miniQA creates a lot of temporary files at runtime, e.g. screenshots and disk image overlays. Specifying this folder allows miniQA to use a permanent directory instead of the default temporary directory, which means:

- snapshots can be cached across sessions, improving test developing experience by reducing wait time
- potential size limitations of the systems temporary directory can be avoided

### `headless` – Enable QEMU's GUI

This defaults to `true`, which should be fine almost all the time (remember that the VM screen is shown in the webui). You can toggle it to `false` for debugging; QEMU will open a window with its own UI in that case.

Make sure to disable this in any headless environments (e.g. CI) to prevent runtime errors.

Note that for tinkering around with your VM image directly, it's best to use `miniqa tinker`, which will launch a temporary VM with all your configured options that is decoupled from your test cases.

### `qemu_args` – Configure Additional QEMU Arguments

A list of arguments that will be appended to the generated default QEMU command. You can add disks or devices and configure raw options here.

### `use_ovmf` – Configure OVMF

OVMF is required for some systems to boot, as the built-in bios is often not enough. You can just install OVMF in your system and set this to true; miniQA will then attempt to locate and use your system installation.

You can also specify OVMF paths manually:

```yaml
use_ovmf:
    code_path: <string>|<list of string>  # path to OVMF_CODE.fd
    vars_path: <string>|<list of string>  # path to OVMF_VARS.fd
```

### `serve_assets` – Add Files or Folders to the Asset Server

The asset server allows accessing files on the host from within your VM via HTTP. You can specifiy which files and folder are available like this:

```yaml
serve_assets:
    - ./assets              # serves all files under ./assets as "${ASSETS_SERVER_ADDR}/assets/*" to the VM
    - ./documentation:docs  # serves ./documentation, but exposes it as "${ASSETS_SERVER_ADDR}/docs/*" to the VM
```

### `env` – Specify Global Variables

The `env` field in your `miniqa.yml` allows you to configure test-suite-wide variables of any type that can be reused across test cases.

### `ignore_regions` – Specify Global Regions to Ignore

Often, systems will have areas that are subject to regular or unpredictable change, e.g. the system clock display. These might interfere with image matching, which is why you can specify them globally here:

```yaml
ignore_regions:
    - 45% 0% 5% 55%
```
