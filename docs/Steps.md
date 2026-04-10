
# miniQA – Steps Reference

## Built-in Steps

### Input Steps

#### `key_press` – Press a Key

```yaml
- key_press: <QemuKeyCode>
```

#### `key_release` – Release a Key

```yaml
- key_release: <QemuKeyCode>
```

#### `invoke_key` – Press and Release a Key

```yaml
- invoke_key: <QemuKeyCode>
```

#### `invoke_keys` – Invoke Multiple Keys

Invoke (=press and release) multiple keys. Via the `sequential` parameter, you can control whether they should be invoked one after the other, or at the same time (in the latter case, keys are pressed in order and then released in reverse order).

```yaml
- invoke_keys: <list of QemuKeyCode>
  sequential: <bool>  # optional; default: true
  speed: <Speed>      # optional
```

#### `type_text` – Write a String Of Characters

Converts the given string into a list of key events, which are then sent sequentially.

```yaml
- type_text: <string>
  speed: <Speed>      # optional
```

#### `mouse_move` – Move the Mouse

```yaml
- mouse_move: <Position>|<MouseButtonArgs>
```

#### `mouse_press` – Press a Mouse Button

```yaml
- mouse_press: <Position>|<MouseButtonArgs>  # value is optional; default: current mouse position
  button: 
```

#### `mouse_release` – Release a Mouse Button

```yaml
- mouse_release: <Position>|<MouseButtonArgs>  # value is optional; default: current mouse position
```

#### `click` – Press and Release a Mouse Button

```yaml
- click: <Position>|<MouseButtonArgs>  # value is optional; default: current mouse position
```

#### `touch_press` – Press Down on the Touchscreen

```yaml
- touch_press: <TouchArgs>|<Position>
```

#### `touch_move` – Move a Finger on the Touchscreen

```yaml
- touch_move: <TouchArgs>|<Position>
```

#### `touch_release` – Lift a Finger from the Touchscreen

```yaml
- touch_release: <TouchArgs>|<Position>
```


#### `touch` – Perform a Gesture on the Touchscreen

```yaml
- touch: <TouchArgs>|<Position>|<list of (TouchArgs|Position)>
  speed: <Speed>      # optional
```


### Control Steps

#### `sleep` – Sleep for a Fixed Time

```yaml
- sleep: <Duration>
```

#### `wait` – Wait for a Condition to be Met

This is likely the most important step to miniQA's test system; it waits for a certain condition to be met by periodically checking within the specified timeout. If the condition is not met within the timeout, the test will fail.

Usage options:
```yaml
- wait:
    for: <string>               # name of a reference screenshot to wait for
    diff: <float>%              # optional; difference tolerance, default: 1%
```
```yaml
- wait:
    for:
      dominant_color: <Color>
    diff: <float>%              # optional; difference tolerance, default: 1%
```
```yaml
- wait:                         # awaits any screen change
    diff: <float>%              # optional; min required difference, default: 1%
```
```yaml
- wait:
    for: <FindElement>
```

All usage options also accept these arguments:
```yaml
    check_interval: <Duration>           # optional; default based on `timeout`
    timeout: <Duration>                  # optional; default: 30s
    regions: <Region>|<list of Regions>  # optional
```


#### `snapshot` – Create a Snapshot of the VM

Snapshots capture the entire disk, memory and CPU state of the VM. They can be restored by another test using the `from` field; when doing so, that test will continue from the exact state the present test was in at this `snapshot` step.

> Note: There is an important known issue – In a test that has a `from` field, creating a "nested" snapshot is very slow; this appears to be an issue an QEMU. It is therefore advisable to avoid creating nested snapshots.

```yaml
- snapshot: <string>  # the name/tag of the snapshot, e.g. "my_snapshot"
```

#### `screenshot` – Create and Validate a Screenshot

This step creates a screenshot of the VM, then, if a reference screenshot with the same name exists, matches it against this screenshot (the test fails on mismatch); if no reference screenshot with this name exists, it will be created by this step.

> This step is of somewhat limited usability, since the `wait` step is a better fit for almost all usecases. However, you can use it to create reference screenshots in scenarios where manually doing so is not feasible.

```yaml
- screenshot:
    name: <string>
    max_diff: <float>%
    regions: <Region>|<list of Region>
```

#### `assert` – Assert the Immediate Presence of an Element

This step checks for an elements immediate presence (like `wait` with an effectively 0 timeout), and fails the test if it is not present.

```yaml
- assert: <FindElement>
```

## Custom Steps

You can create custom steps by specifying them in the `defs` field of your test case file – read more about that [here](./Test%20Case%20Files.md#defs--defining-reusable-custom-steps).

## Value Types

### `Duration`

Formatting options:

```yaml
<float>s
```
```yaml
<float>ms
```

Examples:

```yaml
0.2s
```
```yaml
200ms
```

### `QemuKeyCode`

A [QCode](https://qemu-project.gitlab.io/qemu/interop/qemu-qmp-ref.html#enum-QMP-ui.QKeyCode) string.

Examples:

```yaml
ret
```
```yaml
ctrl
```
```yaml
up
```

### `Position`

Formatting Options:

```yaml
(<float>%|<int>px) (<float>%|<int>px)
```
```yaml
x: (<float>%|<int>px)
y: (<float>%|<int>px)
```
```yaml
[<int>, <int>]
```
```yaml
right | left | top | bottom | center | top-left | top-right | bottom-left | bottom-right | top-center | right-center | bottom-center | left-center
```
```yaml
<FindElement>
```


### `FindElement`

Formatting options:

```yaml
find:
    text: <string>
    location_hint: <Position>  # optional, improves performance
    background_color: <Color>  # optional, constraints results
```


### `Region`

Formatting options:

```yaml
(<float>%|<int>px) (<float>%|<int>px) (<float>%|<int>px) (<float>%|<int>px)  # x, y, width, height
```
```yaml
x: (<float>%|<int>px)
y: (<float>%|<int>px)
width: (<float>%|<int>px)
height: (<float>%|<int>px)
```

Examples:

```yaml
20% 40% 25% 10%
```
```yaml
20% 40% 250px 100px
```


### `Color`

Formatting options:

```yaml
"#<hex RGB string>"  # just like CSS
```

Examples:

```yaml
"#fafafb"
```
```yaml
"#cb45ff"
```

> Remember to quote color strings, as they'll be interpreted as YAML comments otherwise.

### `Speed`

Formatting options:

```yaml
slow | slower | normal | faster | fast
```
```yaml
<float>%
```

### `MouseButtonArgs`

Formatting options:

```yaml
position: <Position>
button: left | middle | right   # optional; default: left
```

### `TouchArgs`

Formatting options:

```yaml
position: <Position>
slot: <int>            # optional; default: 0
```
