"""Lesson 35: an operating-system sandbox for shell commands, where the OS offers one.

Everything before this lesson reads *text*: the command, the paths, the words. A program can still
build a path while it runs (`'.g' + 'it'`), and a script can do anything the user can. A sandbox
doesn't read anything. It changes what the process is *able* to do: it may write only inside the
workspace (and a temporary folder), the protected folders inside the workspace (`.git`, `.harness`,
`.github/workflows` ...) are read-only even there, and, if asked, the network is cut off.

    Linux     bubblewrap (`bwrap`), usually a package away: `apt install bubblewrap`
    macOS     `sandbox-exec`, which ships with the system (deprecated by Apple, still present)
    Windows   nothing equivalent that can be started like this from a script. Use WSL 2, a container or
              a virtual machine for projects you don't trust.

`detect()` finds one, `Sandbox.wrap()` turns a command's argv into the argv that runs it inside. The
wrapping is plain string-building, tested without needing the tool; running it for real needs the OS.
"""
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from harness.security.permissions import PROTECTED_DIRS, PROTECTED_FILES

MODES = ("off", "auto", "on")
SANDBOX_HELP = {
    "off": "run commands directly",
    "auto": "use an OS sandbox when this machine has one",
    "on": "always use one; with none available, commands are refused",
}
INSTALL_HINT = {"linux": "install bubblewrap (apt install bubblewrap, dnf install bubblewrap, ...)",
                "darwin": "sandbox-exec is part of macOS; it wasn't found on PATH",
                "win32": "Windows has no sandbox we can start; use WSL 2, a container or a virtual machine"}


def protected_paths(root: Path) -> list[Path]:
    """The protected folders and files that exist inside the workspace (a sandbox can only protect
    what is already there)."""
    found = [root / name for name in (*PROTECTED_DIRS, *PROTECTED_FILES)]
    return [p for p in found if p.exists()]


@dataclass
class Sandbox:
    name: str
    program: str

    def wrap(self, argv: list[str], cwd: Path, root: Path, network: bool = True) -> list[str]:
        root = Path(root).resolve()
        if self.name == "bubblewrap":
            return bubblewrap_argv(self.program, argv, Path(cwd).resolve(), root, protected_paths(root), network)
        return seatbelt_argv(self.program, argv, root, protected_paths(root), network)

    def describe(self, network: bool = True) -> str:
        net = "network allowed" if network else "network blocked"
        return (f"commands run in a {self.name} sandbox: they can write only inside the workspace "
                f"(and a temporary folder), protected folders are read-only, {net}")


def bubblewrap_argv(program: str, argv: list[str], cwd: Path, root: Path, protected: list[Path], network: bool) -> list[str]:
    """bwrap: the whole file system read-only, then the workspace writable, then the protected places
    read-only again (a later mount of the same path wins). A fresh /tmp, /proc and /dev."""
    out = [program, "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
           "--bind", str(root), str(root)]
    for path in protected:
        out += ["--ro-bind", str(path), str(path)]
    out += ["--unshare-pid", "--die-with-parent", "--new-session"]
    if not network:
        out.append("--unshare-net")
    return out + ["--chdir", str(cwd), "--", *argv]


def seatbelt_quote(path: Path | str) -> str:
    return '"' + str(path).replace("\\", "\\\\").replace('"', '\\"') + '"'


def seatbelt_profile(root: Path, protected: list[Path], network: bool) -> str:
    """A sandbox-exec profile. The last rule that matches wins, so the allowances come first and the
    protected places are denied after them."""
    lines = ["(version 1)", "(allow default)", "(deny file-write*)",
             f"(allow file-write* (subpath {seatbelt_quote(root)}) (subpath \"/private/tmp\") "
             "(subpath \"/private/var/folders\") (subpath \"/dev\"))"]
    lines += [f"(deny file-write* (subpath {seatbelt_quote(p)}))" for p in protected]
    if not network:
        lines.append("(deny network*)")
    return "\n".join(lines)


def seatbelt_argv(program: str, argv: list[str], root: Path, protected: list[Path], network: bool) -> list[str]:
    return [program, "-p", seatbelt_profile(root, protected, network), *argv]


def detect(platform: str = sys.platform, which: Callable[[str], str | None] = shutil.which) -> Sandbox | None:
    """The sandbox this machine offers, or None."""
    if platform.startswith("linux"):
        found = which("bwrap")
        return Sandbox("bubblewrap", found) if found else None
    if platform == "darwin":
        found = which("sandbox-exec")
        return Sandbox("sandbox-exec", found) if found else None
    return None


def hint(platform: str = sys.platform) -> str:
    return INSTALL_HINT["linux" if platform.startswith("linux") else platform] if (
        platform.startswith("linux") or platform in INSTALL_HINT) else "this system has no supported sandbox"
