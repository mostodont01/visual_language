# Writing VL nodes

How to write your own nodes for Visual Language (VL), from the first file
to talking to the robot's hardware.

## 1. What a node is

A node is two things:

- **A JSON file:** what VL shows in the editor (title, sockets, settings,
  color group) and which code files belong to the node.
- **C++ code:** a class that does the work. VL copies it into the generated
  program and compiles it.

A good folder layout (one JSON per node; the C++ files in `src/`):

```
robocars/
    nodes/
        read_lidar.json
        set_motor_speed.json
        src/
            read_lidar.hpp
            read_lidar.cpp
            set_motor_speed.hpp
            set_motor_speed.cpp
            lidar_scan.hpp         a custom data type, shared by several nodes
    robot.vl                       the project (the graph)
```

VL's own `examples/robocars/` folder has working examples of every kind of
node described here.

## 2. Your first node, step by step

A node that multiplies a number by a factor.

**`nodes/scale.json`**

```json
{
    "id": "scale",
    "class": "Scale",
    "code": ["src/scale.hpp"],
    "group": "Math",
    "title": "Scale",
    "description": "Multiplies the value by a factor",
    "inputs": [
        { "id": "value", "name": "Value", "type": "int32" },
        { "id": "factor", "name": "Factor", "type": "float32",
          "widget": { "kind": "number", "default": 1.0 } }
    ],
    "outputs": [
        { "id": "result", "name": "Result", "type": "int32" }
    ]
}
```

**`nodes/src/scale.hpp`**

```cpp
#pragma once
#include "vl/runtime.hpp"

// result = value * factor
class Scale : public vl::Node {
public:
    vl::Input<int32_t> value;
    vl::Input<float> factor;
    vl::Output<int32_t> result;

    void process() override {
        result.set(static_cast<int32_t>(value.get() * factor.get()));
    }
};
```

**Use it:**

1. In VL: **File → Import Nodes…** (Ctrl+I) and pick `scale.json`. You
   can select several JSON files at once.
2. Press **Shift+A** in the graph and search for "Scale".
3. Connect it, then press **Compile** (Ctrl+B).

**Important:** importing *copies* the JSON and the code into the `.vl`
project file. After you change the code, update the copy: **Settings** tab →
the node in *Imported nodes* → **Re-import…**. Importing a file with the same
`id` again also asks whether to replace the node.

## 3. The JSON file

| Key | Required | Meaning |
| --- | --- | --- |
| `id` | yes | Unique name of the node type. Saved in project files, so **don't rename it** after you've used the node. Must not be the id of a built-in node (`add`, `threshold`, ...). |
| `class` | yes | The C++ class that implements the node. |
| `code` | yes | The node's code files, relative to the JSON. A list, or one path as a string. They must be inside the JSON's folder (subfolders are fine, `..` isn't). |
| `title` | no | Name shown on the node and in the Shift+A search. Default: the id. |
| `description` | no | Shown in the Shift+A menu. |
| `group` | no | Section in the Shift+A menu, also gives the node its color. Default `"Other"`. New groups get a color when you import the node; change it in the **Settings** tab. |
| `inputs` | no | Sockets on the left. |
| `outputs` | no | Sockets on the right. |
| `settings` | no | Values edited on the node itself, with no socket. |
| `types` | no | Custom data types (section 6). |
| `app_widget` | no | The node shows something in the compiled app's window (section 7). |

### Inputs, outputs and settings

```json
{ "id": "speed", "name": "Speed", "type": "int32",
  "widget": { "kind": "number", "default": 0, "min": -100, "max": 100 } }
```

- `id`: becomes the C++ member name. Rules:
  - letters, digits and `_`, not starting with a digit;
  - not starting with `vl`;
  - unique within the node; inputs, outputs and settings all share the same names;
  - not a C++ keyword (`int`, `class`, `delete`, ...);
  - not the name of a `vl::Node` function (`setup`, `process`, `drawWidget`,
    `runEvery`, `requestProcess`).
- `name`: label shown in the editor. Default: the id.
- `type`: the data type. Wires only connect sockets with *exactly* the same type.
- `widget`:
  - **inputs:** optional. A field shown while nothing is connected; its
    value is used then. Without a widget, the input must be connected.
  - **outputs:** not allowed.
  - **settings:** required.

### Data types

| Type | C++ type | Note |
| --- | --- | --- |
| `int32` | `int32_t` | whole numbers |
| `float32` | `float` | decimals |
| `bool` | `bool` | true / false |
| `string` | `std::string` | text |
| anything else | your own | must be declared in `types` (section 6) |

Settings and fields need one of the four built-in types.

### Widget kinds

| Kind | Options | Default if omitted |
| --- | --- | --- |
| `number` | `default`, `min`, `max` | `0` |
| `string` | `default` | `""` |
| `select` | `options` (required, a list of strings), `default` | first option |
| `checkbox` | `default` | `false` |

A `number` is a whole number for `int32` and a decimal for `float32`.
`"widget": "number"` is short for `{ "kind": "number" }`. A `select` gives a
`string` in C++ (the chosen option's text).

JSON has no comments. Put explanations into `description` or the C++ code.

## 4. The C++ class

```cpp
#pragma once
#include <string>
#include "vl/runtime.hpp"

class MyNode : public vl::Node {
public:
    // One member per input, output and setting, named after its id.
    vl::Input<int32_t> speed;           // input:   read with speed.get()
    vl::Output<int32_t> result;         // output:  send with result.set(x)
    std::string port = "/dev/ttyUSB0";  // setting: a plain member

    void setup() override;     // optional: once at the start
    void process() override;   // the node's work

private:
    int fd_ = -1;              // your own state: private, ending in _
};
```

- **Members:**
  - inputs are `vl::Input<T>`;
  - outputs are `vl::Output<T>`;
  - settings are plain members of the setting's type.
  - All of them must be `public`.
- **Settings** get their values from the editor before `setup()` runs. The
  value written in the class (`= "/dev/ttyUSB0"`) is only a fallback.
- **`input.get()`** returns the input's latest value.
- **`output.set(value)`** sends a value to everything connected. Call it as
  often as you like (or not at all, if there is nothing new).
- **Your own state:** keep it in `private` members. Their names must not
  start with `vl`.

### When does what run?

| Function | Runs |
| --- | --- |
| `setup()` | Once at the start, after the settings are set. Open devices here. |
| `process()` | Once at the start. After that, whenever **any input receives a new value**, but only once **every required** input has had a value. It uses the latest value of every input. Optional inputs and non-triggering inputs change this (see below). |
| `runEvery(seconds)` | Call it in `setup()`: `process()` then also runs every `seconds`. Use it for sensors and anything that polls. |
| `requestProcess()` | Run `process()` again soon, e.g. after a widget changed something. |
| destructor `~MyNode()` | When the program ends normally (window closed, Esc). Close devices, stop motors. **Not** run on Ctrl+C or a crash. |

More rules:

- **The program is single-threaded.** All nodes run one after another, so
  **never block or sleep** in `process()`. A blocking `read()` stops the whole
  robot. Poll with `runEvery()` and non-blocking reads instead (section 8).
- **When the program ends:**
  - **Without a window:** the program ends when nothing can happen any more.
    A robot program needs at least one node with `runEvery()` to keep running.
  - **With a window:** it runs until the window is closed or Esc is pressed.
    Timers are checked once per frame, so `runEvery()` faster than about
    60 Hz runs at the frame rate.
- **Feedback loops:** a wire that loops back (A → B → A) doesn't start a run;
  it only updates the value. Loops can't run forever. To choose *which* wire
  of a loop that is, make its input non-triggering (`"triggers": false`).
- **Optional inputs** (`"optional": true` in the JSON, drawn as a diamond)
  never hold the node back. Unconnected, they keep their `"default"` (or
  the field's value). Connected, they keep the default until the first
  value arrives. `input.connected()` tells whether a wire is attached,
  `input.hasValue()` whether a real value has arrived.
- **Non-triggering inputs** (`"triggers": false`, label in italics) store
  new values without running the node. Example: a node that should run on
  every new LiDAR scan and just use the latest position: the scan input
  triggers, the position input doesn't.
- **Printing:** `std::printf` shows up in VL's build log when you run the
  program from VL, or in the terminal on the robot.

### Writing the code in a `.cpp` file

Bigger nodes: declare the class in the `.hpp`, write the functions in a `.cpp`.
List **both** files in `code`. Only `.cpp`, `.cc` and `.cxx` files are compiled.
Headers are included by the generated program: each node type is compiled
in its own file that includes only that node's headers, so a header must
`#include` everything it uses.

```cpp
// src/set_motor_speed.hpp
#pragma once
#include "vl/runtime.hpp"

class SetMotorSpeed : public vl::Node {
public:
    vl::Input<int32_t> speed;
    void process() override;
};
```

```cpp
// src/set_motor_speed.cpp
#include "set_motor_speed.hpp"
#include <cstdio>

void SetMotorSpeed::process() {
    std::printf("[motor] speed %d\n", speed.get());
}
```

### Including files

- `#include "vl/runtime.hpp"`: always needed.
- `#include "vl/widgets.hpp"`: in nodes with an app widget.
- Your own files: relative to the file that includes them, e.g.
  `#include "lidar_scan.hpp"` from another file in `src/`.

### Names must be unique across all nodes

Every node's header ends up in one program. So:

- Every **class name** must be unique across all your nodes.
- Helper functions and constants written in a header: mark them `inline`
  (`inline float clamp01(float x) { ... }`). In a `.cpp`, put them in an
  unnamed `namespace { ... }`.
- Two nodes can't share a helper header (except a type header, see below):
  each node gets its own copy, and the program would see everything twice.
  Keep shared code in a type header or in each node.

## 5. Common node patterns

**Source** (no inputs, produces data on a timer):

```cpp
class ReadLidar : public vl::Node {
public:
    float frequency = 10;               // setting
    vl::Output<LidarScan> scan;

    void setup() override { runEvery(1.0 / frequency); }
    void process() override { /* read the sensor, then */ /* scan.set(s); */ }
};
```

**Transform** (inputs → outputs): see `Scale` above.

**Sink** (only inputs; does something with the value):

```cpp
class SetMotorSpeed : public vl::Node {
public:
    vl::Input<int32_t> speed;
    void process() override { /* send speed.get() to the motor */ }
};
```

**Constant** (no inputs, sends once at the start):

```cpp
class ConstantInt : public vl::Node {
public:
    int32_t number = 0;                 // setting
    vl::Output<int32_t> value;
    void process() override { value.set(number); }
};
```

## 6. Custom data types

To pass something bigger than a number through a wire, like a whole LiDAR
scan, define a C++ type in its own header:

```cpp
// src/lidar_scan.hpp
#pragma once
#include <vector>

// One LiDAR revolution: ranges[i] is the distance in metres at i degrees.
struct LidarScan {
    std::vector<float> ranges;
};
```

Then declare it in the JSON of **every node that uses it**, and list the
header in `code`:

```json
"code": ["src/read_lidar.hpp", "src/read_lidar.cpp", "src/lidar_scan.hpp"],
"types": {
    "LidarScan": { "cpp": "LidarScan", "header": "src/lidar_scan.hpp" }
},
"outputs": [ { "id": "scan", "name": "Scan", "type": "LidarScan" } ]
```

- `"LidarScan"` (the key) is the type name used in sockets. `cpp` is the C++
  type, which may include a namespace (`robo::LidarScan`).
- Several nodes ship the same header. VL includes it only once, so **the
  header file must be identical in all of them**. Keep one file in `src/`
  that all the JSONs point to, and re-import every node using it after you
  change it.
- The type needs a default constructor (`LidarScan{}`); inputs start with it.
- The new type gets a wire color when imported. Change it in the
  **Settings** tab.
- Values are copied along wires. A few thousand numbers per frame is no
  problem.

## 7. App widgets: showing things on the robot's screen

A node can draw into the compiled program's window, for example a number,
a button or a LiDAR picture. The window opens only if at least one such node
is in the graph with its eye open. The widgets are laid out automatically,
fullscreen.

JSON:

```json
"app_widget": { "title_setting": "label" },
"settings": [
    { "id": "label", "name": "Label", "type": "string", "app_widget_only": true,
      "widget": { "kind": "string", "default": "Speed" } }
]
```

- `app_widget` gives the node an **eye** in its header to show or hide its
  widget.
- `title_setting` (optional): a setting whose value is the widget's title.
  Without it, the node's title is used.
- `"app_widget_only": true`: a setting that's only shown while the eye is open.

C++: override `drawWidget()` and draw with
[Dear ImGui](https://github.com/ocornut/imgui). It **must** be inside
`#ifdef VL_GUI`, because programs without a window are built without ImGui.

```cpp
#pragma once
#include <string>
#include "vl/runtime.hpp"
#include "vl/widgets.hpp"

class SpeedSlider : public vl::Node {
public:
    std::string label;
    vl::Output<int32_t> speed;

    void process() override { speed.set(current_); }

#ifdef VL_GUI
    void drawWidget() override {
        ImGui::SetNextItemWidth(-1);                 // full width
        if (ImGui::SliderInt("##speed", &current_, -100, 100))
            requestProcess();                        // send the new value
        if (ImGui::Button("STOP")) {
            current_ = 0;
            requestProcess();
        }
    }
#endif

private:
    int current_ = 0;
};
```

Useful ImGui calls:
- `ImGui::Text("%d mm", value)` and `ImGui::TextDisabled("waiting...")` for text;
- `ImGui::Button`, `SliderInt` and `SliderFloat`, `Checkbox`, `InputInt`;
- `ImGui::ProgressBar(0.0f..1.0f)`;
- for drawing (e.g. a LiDAR view): `ImGui::GetWindowDrawList()->AddLine/AddCircleFilled(...)`.

Labels starting with `##` are hidden; they only need to be unique within the
widget.

## 8. Talking to hardware on the Raspberry Pi

### What you can use

- The compiled program can use the **C++ standard library** and the
  **Linux system interface**: `open/read/write/ioctl`, serial ports,
  `/dev/i2c-*`, `/dev/spidev*`, `/sys/...` files.
- **It can't link extra libraries yet** (libgpiod, pigpio, wiringPi, ...). If
  you need one, that's a VL feature to add first.

### Linux-only code

Graphs are also compiled for your PC or Windows to test them, so put Linux-only
code inside `#ifdef __linux__` and add a fallback for elsewhere. A simulated
value or a `printf` is fine. Then the same graph compiles everywhere.

### Serial (USB-serial adapters, many LiDARs, motor controllers)

```cpp
// src/serial_motor.hpp
#pragma once
#include <string>
#include "vl/runtime.hpp"

class SerialMotor : public vl::Node {
public:
    std::string port = "/dev/ttyUSB0";   // setting (string widget)
    vl::Input<int32_t> speed;

    ~SerialMotor() override;
    void setup() override;
    void process() override;

private:
    int fd_ = -1;
};
```

```cpp
// src/serial_motor.cpp
#include "serial_motor.hpp"
#include <cstdio>

#ifdef __linux__
#include <fcntl.h>
#include <termios.h>
#include <unistd.h>
#endif

void SerialMotor::setup() {
#ifdef __linux__
    fd_ = open(port.c_str(), O_RDWR | O_NOCTTY | O_NONBLOCK);
    if (fd_ < 0) {
        std::perror(("serial motor: " + port).c_str());
        return;
    }
    termios tty{};
    tcgetattr(fd_, &tty);
    cfmakeraw(&tty);                 // bytes as they are, no line editing
    cfsetispeed(&tty, B115200);
    cfsetospeed(&tty, B115200);
    tcsetattr(fd_, TCSANOW, &tty);
#endif
}

void SerialMotor::process() {
    char line[32];
    int n = std::snprintf(line, sizeof line, "S%d\n", speed.get());
#ifdef __linux__
    if (fd_ >= 0)
        write(fd_, line, n);
#else
    std::fwrite(line, 1, n, stdout);  // no hardware: just print it
#endif
}

SerialMotor::~SerialMotor() {
#ifdef __linux__
    if (fd_ >= 0) {
        write(fd_, "S0\n", 3);       // stop the motor when the program ends
        close(fd_);
    }
#endif
}
```

**Reading a serial device:**
- Call `runEvery(0.01)` in `setup()`.
- In `process()`, `read()` whatever bytes are there. With `O_NONBLOCK`, it
  returns -1 right away when nothing has arrived.
- Collect the bytes in a member buffer until you have a whole message, then
  `set()` the output.

### I2C (sensors, PWM boards like the PCA9685, motor HATs)

Enable it once on the Pi: `sudo raspi-config` → *Interface Options → I2C*.
The header pins 3/5 are `/dev/i2c-1`.

```cpp
#include <fcntl.h>
#include <linux/i2c-dev.h>
#include <sys/ioctl.h>
#include <unistd.h>

fd_ = open("/dev/i2c-1", O_RDWR);
ioctl(fd_, I2C_SLAVE, 0x40);          // the device's address
unsigned char cmd[2] = {0x00, 0x10};  // register, value
write(fd_, cmd, 2);
```

### PWM (driving motors or servos directly)

The Pi 5 has hardware PWM, controlled through files in `/sys/class/pwm/`.
It needs `dtoverlay=pwm-2chan` in `/boot/firmware/config.txt`.
- Turn a channel on by writing `0` to `export`.
- Then write `period`, `duty_cycle` (both in nanoseconds) and `enable` in
  `pwmchip*/pwm0/`.
- Plain `std::ofstream` writes are enough.

### Permissions

Your user on the Pi needs access to the devices:

```bash
sudo usermod -aG dialout,i2c,gpio,video $USER   # then log out and back in
```

### Safety

- **Motors:** stop them in the node's destructor. But Ctrl+C, a crash or
  unplugging skips it. If your motor controller has a **timeout** ("stop if
  no command for 0.5 s"), turn it on, and send the speed regularly (e.g.
  `runEvery(0.1)`), not only when it changes.
- **Testing:** test new motor code with the wheels off the ground.

## 9. Flows: start-up, emergencies and other sequences

The graph you've built so far is the **main tree**: dataflow, everything runs
whenever its inputs change. Some things are sequences instead: "spin up the
LiDAR, wait until it's ready, wait for the start button, then race", or "on
the emergency switch: stop, wait until it's released, start over". Those are
**flows**: nodes connected by thick white **exec** wires that run one after
another, like Blender's or Unreal's execution wires.

```
On Start → Wait Until [LiDAR ready] → Wait Until [start button] → Start Main
On Event [emergency switch or battery low] (priority 10)
         → Log "stopped" → Wait Until [all clear] → Restart
```

- **On Start → … → Start Main** is the start-up flow. The main tree only
  starts when it reaches Start Main. Without an On Start, the main tree
  starts at once (like before flows existed).
- **On Event** fires when its `Trigger` turns true, in any phase. It stops
  the main tree (or the start-up flow, or a lower-priority event flow) and
  runs its own flow, which ends at **Resume Main** (back to the main tree; an
  interrupted start-up flow starts over), **Restart** (every node's
  `reset()`, then the start-up flow again) or **Stop Program**.
- In between: **Wait** (seconds), **Wait Until** (a bool), **Branch** (true /
  false), **Log** (prints a message). An exec wire may lead back to an
  earlier node (a loop), but give the loop a Wait.
- **Which data nodes run when:** in the main phase all of them. During a flow
  only those the flow needs: the ones feeding its nodes' inputs (and the ones
  fed by its nodes' outputs). The nodes feeding On Event triggers always run,
  so a battery monitor or emergency switch is watched all the time.
- An exec output takes one wire; an exec input can take many. Wires that
  don't lead to an end node end the flow there (the issues list warns).

### `stop()` and `reset()`

Two more functions a node can override:

| Function | Runs |
| --- | --- |
| `stop()` | When the node stops running because an event flow stopped the main tree, and when the program ends (window closed, Esc, **Ctrl+C**, SIGTERM). Make the hardware safe here: a motor node sets its outputs to zero. May run more than once. |
| `reset()` | Before a Restart runs the start-up flow again: forget state from the last run (counters, "already started" flags...). |

With `stop()` in the motor node, "the robot stops" doesn't depend on any wiring.

### Writing your own flow nodes

A flow node has `"type": "exec"` sockets in its JSON and derives from
`vl::FlowNode`. Exec sockets have no C++ member; exec outputs are numbered in
JSON order.

```json
{
    "id": "drive_until_wall", "class": "DriveUntilWall", "code": ["src/drive_until_wall.hpp"],
    "inputs": [
        { "id": "run", "name": "Run", "type": "exec" },
        { "id": "distance", "name": "Distance", "type": "float32" }
    ],
    "outputs": [
        { "id": "then", "name": "Then", "type": "exec" },
        { "id": "speed", "name": "Speed", "type": "float32" }
    ]
}
```

```cpp
class DriveUntilWall : public vl::FlowNode {
public:
    vl::Input<float> distance;
    vl::Output<float> speed;

    void start() override { speed.set(0.3f); }     // execution arrived here
    int update() override {                        // after start(), then on every new input
        if (distance.get() > 0.2f)
            return Running;                        // stay here
        speed.set(0);
        return 0;                                  // continue on exec output 0 ("then")
    }
};
```

`update()` runs right after `start()` and then whenever an input changes, its
timer fires (`runEvery()`, or `wakeAt(time)` for one wake-up) or it calls
`requestProcess()`. Never block in it. `Running` means "not done yet".

## 10. From graph to robot

1. Build the graph in VL.
2. **Compile** → pick the target **Linux ARM64**. The first build takes a few
   minutes (it downloads Dear ImGui and SDL2). The program ends up in the
   output folder (default: `build/` next to the project).
   - If VL says build tools are missing, run
     `.venv/bin/pip install -r requirements.txt` in the VL folder. That
     installs Zig, which builds programs for the Pi.
3. Copy it to the robot and run it:

   ```bash
   scp build/robot build/robot.values.json pi@<robot-ip>:~/
   ssh pi@<robot-ip> ./robot
   ```

   `robot.values.json` holds the settings and input values; the program
   needs it next to it. Changing only values doesn't need a new program:
   compile again and copy just the `.values.json`.

   With the Pi's desktop running, it opens fullscreen. On Raspberry Pi OS
   Lite (no desktop) it draws straight to the screen and needs
   `sudo apt install libgbm1 libegl1 libgles2` once.
4. Test logic on your PC first: compile the same graph for **Linux x86-64**
   and run it from VL.

## 11. When something goes wrong

| Problem | Cause |
| --- | --- |
| Import error naming a key | The JSON is broken or a rule from section 3 is broken. The message names the file and the key. |
| `code file not found` | A path in `code` is wrong (relative to the JSON). |
| Compile error in your code | It's shown in VL's build log, with the file and line. The file paths there point into the build folder (`nodes/<id>/...`). Fix the original and **re-import**. |
| Code changes have no effect | You didn't re-import the node (section 2). |
| `redefinition of class ...` | Two nodes use the same class name or share a helper header (section 4). |
| `Type 'X' has no C++ definition` | A socket type that isn't built in isn't declared in `types`. |
| `Type 'X' is defined differently` | Two nodes ship different versions of the type header. Re-import all of them. |
| Node never runs | One of its inputs never got a value. All inputs need one before `process()` runs. |
| Program exits right away (no window) | No node uses `runEvery()`, so nothing keeps it running. |
| Robot freezes | Something blocks or sleeps inside `process()` (section 4). |
| `Permission denied` on `/dev/...` | Groups missing (section 8). |

## Checklist for a new node

- [ ] `id` unique and final, `class` unique, `title`, `group`, `description`.
- [ ] Every code file listed in `code`; type headers declared in `types`.
- [ ] One public C++ member per input, output and setting, named after its id,
      with the matching type.
- [ ] `#pragma once` in every header; `#include "vl/runtime.hpp"`.
- [ ] Nothing blocks in `process()`; sources use `runEvery()`.
- [ ] Hardware code in `#ifdef __linux__`, with a fallback.
- [ ] Widgets inside `#ifdef VL_GUI`.
- [ ] Devices closed and motors stopped in the destructor.
- [ ] Imported (or re-imported) into the project after the last change.
