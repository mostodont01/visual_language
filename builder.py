"""Runs CMake on a generated project in the background and collects the log.

The UI shows `log` and `status` while the build runs. If the tools needed
for the chosen target are missing, nothing is run: the log says what to
install, and the generated project stays in the output folder.
"""

import importlib.util
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QUrl, Property, Signal, Slot

import compiler

_EXE = ".exe" if sys.platform == "win32" else ""
# In the packaged VL (PyInstaller), CMake, Ninja and Zig come along in tools/.
_BUNDLED = Path(sys._MEIPASS) / "tools" if hasattr(sys, "_MEIPASS") else None


def _find(name: str, bundled: str) -> str:
    """A program bundled with VL, on PATH, or installed by pip next to Python."""
    candidates = [_BUNDLED / bundled / (name + _EXE)] if _BUNDLED else []
    if found := shutil.which(name):
        candidates.append(Path(found))
    candidates.append(Path(sys.executable).parent / (name + _EXE))   # .venv/bin or .venv\Scripts
    return next((str(c) for c in candidates if c.is_file()), "")


def _zig() -> str:
    """Zig from the packaged VL, the `ziglang` Python package or PATH, or ""."""
    if _BUNDLED:
        return _find("zig", "zig")
    spec = importlib.util.find_spec("ziglang")
    if spec is not None and spec.origin is not None:
        zig = Path(spec.origin).parent / ("zig" + _EXE)
        if zig.exists():
            return str(zig)
    return shutil.which("zig") or ""


def _has_system_sdl2() -> bool:
    return bool(shutil.which("sdl2-config")) or Path("/usr/include/SDL2/SDL.h").exists()


def uses_system_compiler(target: str, gui: bool) -> bool:
    """Native Linux builds use the system's compiler and SDL2 when they are
    installed; everything else is built with Zig, which brings its own."""
    return (target == compiler.host_target() and sys.platform != "win32"
            and any(shutil.which(c) for c in ("c++", "g++", "clang++"))
            and (not gui or _has_system_sdl2()))


def missing_tools(target: str, gui: bool) -> list[str]:
    """Tools needed for this target that aren't installed: cmake, ninja, zig."""
    missing = []
    if not _find("cmake", "cmake/bin"):
        missing.append("cmake")
    if not (_find("ninja", "ninja") or (sys.platform != "win32" and shutil.which("make"))):
        missing.append("ninja")
    if not uses_system_compiler(target, gui) and not _zig():
        missing.append("zig")
    return missing


def _command_line(command: list[str]) -> str:
    """A command as it would be typed, for the log."""
    return " ".join(f'"{part}"' if " " in part else part for part in command)


class Builder(QObject):
    logChanged = Signal()
    statusChanged = Signal()
    # Emitted when a build ends: (success, short summary).
    finished = Signal(bool, str)

    def __init__(self):
        super().__init__()
        self._log: list[str] = []
        self._status = "idle"   # idle, running, succeeded, failed, generated
        self._output_dir = ""
        self._executable = ""
        self._process: QProcess | None = None
        self._steps: list[list[str]] = []

    # -- Properties ---------------------------------------------------------

    @Property(str, notify=logChanged)
    def log(self) -> str:
        return "\n".join(self._log)

    @Property(str, notify=statusChanged)
    def status(self) -> str:
        return self._status

    @Property(bool, notify=statusChanged)
    def running(self) -> bool:
        return self._status == "running"

    @Property(str, notify=statusChanged)
    def outputFolderUrl(self) -> str:
        return QUrl.fromLocalFile(self._output_dir).toString() if self._output_dir else ""

    @Property(str, notify=statusChanged)
    def executable(self) -> str:
        return self._executable

    # -- Used by Project ----------------------------------------------------

    def begin(self):
        """Start a new log for a compile."""
        self.cancel()
        self._log = []
        self._output_dir = ""
        self._executable = ""
        self._set_status("running")
        self.logChanged.emit()

    def append(self, line: str):
        self._log.append(line)
        self.logChanged.emit()

    def fail(self, summary: str):
        self.append("")
        self.append(f"✕ {summary}")
        self._set_status("failed")
        self.finished.emit(False, summary)

    def build(self, output_dir: Path, settings: dict, name: str, gui: bool):
        """Configure and build the generated project with CMake (asynchronously)."""
        self._output_dir = str(output_dir)
        target = settings["target"]

        missing = missing_tools(target, gui)
        if missing:
            self.append("")
            self.append("The C++ project was generated, but it can't be built here yet. Missing: "
                        + ", ".join(missing))
            self.append("Install them with:  " + _command_line(
                [sys.executable, "-m", "pip", "install", "-r", str(Path(__file__).parent / "requirements.txt")]))
            if target == compiler.host_target() and sys.platform != "win32":
                self.append("(Or use the system compiler:  sudo apt install build-essential cmake libsdl2-dev)")
            self.append(f"Or build the project in {output_dir} on the target machine with CMake.")
            self._set_status("generated")
            self.finished.emit(False, "Project generated, not built (missing tools)")
            return

        # One build folder per target and compiler: CMake can't switch compilers in place.
        system = uses_system_compiler(target, gui)
        build_dir = output_dir / "build" / (target if system else target + "-zig")
        cmake, ninja = _find("cmake", "cmake/bin"), _find("ninja", "ninja")
        configure = [cmake, "-S", str(output_dir), "-B", str(build_dir),
                     f"-DCMAKE_BUILD_TYPE={'Release' if settings['build_type'] == 'release' else 'Debug'}"]
        if ninja and not (build_dir / "Makefile").exists():
            configure += ["-G", "Ninja", f"-DCMAKE_MAKE_PROGRAM={ninja}"]
        if not system:
            configure.append(f"-DCMAKE_TOOLCHAIN_FILE={output_dir / compiler.TOOLCHAIN_FILES[target]}")
            configure.append(f"-DVL_ZIG={_zig()}")
        self._steps = [configure, [cmake, "--build", str(build_dir), "--parallel"]]
        self._executable = str(output_dir / compiler.executable_file_name(name, target))
        self._run_next_step()

    @Slot()
    def cancel(self):
        if self._process is not None:
            self._steps = []
            process, self._process = self._process, None
            process.kill()
            process.waitForFinished(2000)
            self.append("")
            self.append("✕ Build cancelled.")
            self._set_status("failed")
            self.finished.emit(False, "Build cancelled")

    # -- Internals ----------------------------------------------------------

    def _set_status(self, status: str):
        if status != self._status:
            self._status = status
            self.statusChanged.emit()

    def _run_next_step(self):
        if not self._steps:
            self.append("")
            self.append(f"✓ Built {self._executable}")
            self._set_status("succeeded")
            self.finished.emit(True, f"Built {Path(self._executable).name}")
            return

        command = self._steps.pop(0)
        self.append("")
        self.append("$ " + _command_line(command))
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(lambda: self._read_output(process))
        process.finished.connect(lambda code, exit_status: self._step_finished(process, code, exit_status))
        process.errorOccurred.connect(lambda error: self._step_error(process, error))
        self._process = process
        process.start(command[0], command[1:])

    def _read_output(self, process: QProcess):
        text = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace")
        for line in text.splitlines():
            self._log.append(line)
        self.logChanged.emit()

    def _step_finished(self, process: QProcess, code: int, exit_status):
        if process is not self._process:
            return  # Cancelled.
        self._read_output(process)
        self._process = None
        if exit_status != QProcess.ExitStatus.NormalExit or code != 0:
            self.fail(f"Build failed (exit code {code}). See the log above.")
        else:
            self._run_next_step()

    def _step_error(self, process: QProcess, error):
        if process is not self._process or error != QProcess.ProcessError.FailedToStart:
            return
        self._process = None
        self.fail(f"Could not start {process.program()}.")
