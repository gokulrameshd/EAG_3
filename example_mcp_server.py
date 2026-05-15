"""
Cross-platform MCP server — teaching example.

Covers the core MCP building blocks in one file:
  1. Tools              — plain functions exposed to the model (math, utils)
  2. File CRUD          — read / write / edit / list / delete (sandboxed)
  3. Resources          — read-only data the model can fetch by URI
  4. HTTP fetch         — reaching the outside world from a tool
  5. SQLite CRUD        — a stateful tool (tiny notes DB)
  6. Shell runner       — a "dangerous" tool guarded by an allowlist
  7. GUI automation     — cross-platform via pyautogui (works on mac/win/linux)
  8. Image tool         — returns a real PNG thumbnail
  9. Prompts            — reusable prompt templates

Run:
  # stdio (how an MCP client launches it)
  python example_mcp_server.py

  # dev inspector
  mcp dev example_mcp_server.py

Install:
  pip install "mcp[cli]" pillow requests pyautogui
"""

from __future__ import annotations

import io
import math
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import requests
from mcp.server.fastmcp import FastMCP, Image
from PIL import Image as PILImage

mcp = FastMCP("TeachingServer")

# ---------------------------------------------------------------------------
# Sandbox — every file/shell tool is confined to this directory.
# Students see an explicit safety boundary instead of "the whole disk".
# ---------------------------------------------------------------------------
SANDBOX = Path(__file__).parent / "sandbox"
SANDBOX.mkdir(exist_ok=True)


def _safe_path(relative: str) -> Path:
    """Resolve `relative` inside SANDBOX and refuse anything that escapes."""
    p = (SANDBOX / relative).resolve()
    if SANDBOX.resolve() not in p.parents and p != SANDBOX.resolve():
        raise ValueError(f"Path '{relative}' escapes the sandbox")
    return p


# ===========================================================================
# 1. TOOLS — simplest case: pure functions
# ===========================================================================

@mcp.tool()
def add(a: float, b: float) -> float:
    """Add two numbers."""
    return a + b


@mcp.tool()
def sqrt(a: float) -> float:
    """Square root of a number."""
    return math.sqrt(a)


@mcp.tool()
def factorial(n: int) -> int:
    """Factorial of a non-negative integer."""
    return math.factorial(n)


@mcp.tool()
def fibonacci(n: int) -> list[int]:
    """First n Fibonacci numbers."""
    seq = [0, 1]
    for _ in range(2, n):
        seq.append(seq[-1] + seq[-2])
    return seq[:n]


def _fov_half_angle_rad(fov_deg: float) -> float:
    """Convert full horizontal FOV (degrees) to half-angle in radians."""
    if fov_deg <= 0 or fov_deg >= 180:
        raise ValueError("fov_deg must be between 0 and 180 (exclusive)")
    return math.radians(fov_deg / 2.0)


def _object_fov_width_mm(working_distance_mm: float, fov_deg: float) -> float:
    """Visible width on the object plane at working distance (mm)."""
    if working_distance_mm <= 0:
        raise ValueError("working_distance_mm must be positive")
    return 2.0 * working_distance_mm * math.tan(_fov_half_angle_rad(fov_deg))


def _sensor_width_mm(focal_length_mm: float, fov_deg: float) -> float:
    """Sensor width implied by focal length and horizontal FOV (mm)."""
    if focal_length_mm <= 0:
        raise ValueError("focal_length_mm must be positive")
    return 2.0 * focal_length_mm * math.tan(_fov_half_angle_rad(fov_deg))


@mcp.tool()
def calculate_sensor_and_focal_length(
    fov_deg: float,
    working_distance_mm: float,
    min_pixels: int,
    min_feature_size_mm: float,
    pixel_pitch_um: float = 3.45,
    aspect_ratio: float = 4 / 3,
) -> dict:
    """Select sensor resolution and lens focal length for a machine-vision setup.

    Uses a pinhole model with horizontal FOV (full angle, degrees).

    Args:
        fov_deg: Horizontal field of view in degrees.
        working_distance_mm: Lens-to-object distance in mm.
        min_pixels: Minimum pixels required across the smallest feature.
        min_feature_size_mm: Smallest feature to resolve, in mm.
        pixel_pitch_um: Sensor pixel pitch in micrometers (default 3.45 µm).
        aspect_ratio: Sensor width / height (default 4:3).

    Returns:
        horizontal_pixels, vertical_pixels, focal_length_mm, sensor_width_mm,
        sensor_height_mm, object_fov_width_mm, pixels_per_mm_on_object.
    """
    if min_pixels < 1:
        raise ValueError("min_pixels must be at least 1")
    if min_feature_size_mm <= 0:
        raise ValueError("min_feature_size_mm must be positive")
    if pixel_pitch_um <= 0:
        raise ValueError("pixel_pitch_um must be positive")
    if aspect_ratio <= 0:
        raise ValueError("aspect_ratio must be positive")

    object_width_mm = _object_fov_width_mm(working_distance_mm, fov_deg)
    pixels_per_mm = min_pixels / min_feature_size_mm
    horizontal_pixels = max(1, math.ceil(object_width_mm * pixels_per_mm))
    vertical_pixels = max(1, math.ceil(horizontal_pixels / aspect_ratio))

    pixel_pitch_mm = pixel_pitch_um / 1000.0
    sensor_width_mm = horizontal_pixels * pixel_pitch_mm
    sensor_height_mm = vertical_pixels * pixel_pitch_mm
    focal_length_mm = sensor_width_mm / (2.0 * math.tan(_fov_half_angle_rad(fov_deg)))

    return {
        "horizontal_pixels": horizontal_pixels,
        "vertical_pixels": vertical_pixels,
        "focal_length_mm": round(focal_length_mm, 3),
        "sensor_width_mm": round(sensor_width_mm, 3),
        "sensor_height_mm": round(sensor_height_mm, 3),
        "object_fov_width_mm": round(object_width_mm, 3),
        "pixels_per_mm_on_object": round(pixels_per_mm, 4),
        "pixel_pitch_um": pixel_pitch_um,
        "aspect_ratio": aspect_ratio,
    }


@mcp.tool()
def calculate_pixels_per_mm(
    working_distance_mm: float,
    sensor_horizontal_pixels: int,
    focal_length_mm: float,
    fov_deg: float | None = None,
    pixel_pitch_um: float | None = 3.45,
    sensor_vertical_pixels: int | None = None,
) -> dict:
    """Compute spatial resolution on the object plane (pixels per mm).

    Object-plane width is computed as ``sensor_width_mm * WD / focal_length``.
    Provide ``fov_deg`` to derive sensor width from the lens, or rely on
    ``pixel_pitch_um`` (default 3.45 µm) with the pixel count.

    Args:
        working_distance_mm: Lens-to-object distance in mm.
        sensor_horizontal_pixels: Sensor horizontal resolution in pixels.
        focal_length_mm: Lens focal length in mm.
        fov_deg: Horizontal FOV in degrees; used to compute sensor width when set.
        pixel_pitch_um: Pixel pitch in µm; used when fov_deg is omitted.
        sensor_vertical_pixels: Optional vertical resolution for vertical px/mm.

    Returns:
        pixels_per_mm_horizontal, object_fov_width_mm, mm_per_pixel_horizontal,
        and optional vertical metrics.
    """
    if sensor_horizontal_pixels < 1:
        raise ValueError("sensor_horizontal_pixels must be at least 1")
    if sensor_vertical_pixels is not None and sensor_vertical_pixels < 1:
        raise ValueError("sensor_vertical_pixels must be at least 1")

    if fov_deg is not None:
        sensor_width_mm = _sensor_width_mm(focal_length_mm, fov_deg)
    elif pixel_pitch_um is not None and pixel_pitch_um > 0:
        sensor_width_mm = sensor_horizontal_pixels * (pixel_pitch_um / 1000.0)
    else:
        raise ValueError("Provide fov_deg or pixel_pitch_um")

    object_width_mm = sensor_width_mm * working_distance_mm / focal_length_mm

    px_per_mm_h = sensor_horizontal_pixels / object_width_mm
    mm_per_px_h = object_width_mm / sensor_horizontal_pixels

    result: dict = {
        "pixels_per_mm_horizontal": round(px_per_mm_h, 4),
        "mm_per_pixel_horizontal": round(mm_per_px_h, 6),
        "object_fov_width_mm": round(object_width_mm, 3),
        "sensor_width_mm": round(sensor_width_mm, 3),
    }

    if sensor_vertical_pixels is not None:
        pitch_mm = (
            sensor_width_mm / sensor_horizontal_pixels
            if fov_deg is not None
            else pixel_pitch_um / 1000.0
        )
        sensor_height_mm = sensor_vertical_pixels * pitch_mm
        object_height_mm = sensor_height_mm * working_distance_mm / focal_length_mm
        px_per_mm_v = sensor_vertical_pixels / object_height_mm
        result["pixels_per_mm_vertical"] = round(px_per_mm_v, 4)
        result["mm_per_pixel_vertical"] = round(object_height_mm / sensor_vertical_pixels, 6)
        result["object_fov_height_mm"] = round(object_height_mm, 3)

    return result


# ===========================================================================
# 2. FILE CRUD — the same primitives Claude itself uses to edit code
# ===========================================================================

@mcp.tool()
def list_files(subdir: str = "") -> list[str]:
    """List files and folders inside the sandbox (optionally under subdir)."""
    target = _safe_path(subdir) if subdir else SANDBOX
    return sorted(str(p.relative_to(SANDBOX)) for p in target.iterdir())


@mcp.tool()
def read_file(path: str) -> str:
    """Read a text file from the sandbox."""
    return _safe_path(path).read_text(encoding="utf-8")


@mcp.tool()
def write_file(path: str, content: str) -> str:
    """Create or overwrite a text file. Parent dirs are created as needed."""
    p = _safe_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} chars to {path}"


@mcp.tool()
def edit_file(path: str, old: str, new: str) -> str:
    """Replace the first occurrence of `old` with `new` in a file.
    Fails if `old` is missing or appears more than once (forces disambiguation).
    """
    p = _safe_path(path)
    text = p.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0:
        raise ValueError("old string not found")
    if count > 1:
        raise ValueError(f"old string matches {count} locations — make it unique")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")
    return f"Edited {path}"


@mcp.tool()
def delete_file(path: str) -> str:
    """Delete a file or an empty directory inside the sandbox."""
    p = _safe_path(path)
    if p.is_dir():
        shutil.rmtree(p)
    else:
        p.unlink()
    return f"Deleted {path}"


# ===========================================================================
# 3. RESOURCES — read-only, addressed by URI (vs tools which are actions)
# ===========================================================================

@mcp.resource("greeting://{name}")
def greeting(name: str) -> str:
    """A personalized hello — demonstrates a parameterized resource URI."""
    return f"Hello, {name}!"


@mcp.resource("sandbox://{path}")
def sandbox_file(path: str) -> str:
    """Expose sandbox files as a resource the client can attach as context."""
    return _safe_path(path).read_text(encoding="utf-8")


# ===========================================================================
# 4. HTTP FETCH — bridging MCP to the outside world
# ===========================================================================

@mcp.tool()
def fetch_url(url: str, max_chars: int = 2000) -> str:
    """GET a URL and return the (truncated) response body."""
    r = requests.get(url, timeout=10)
    r.raise_for_status()
    body = r.text
    return body if len(body) <= max_chars else body[:max_chars] + "\n...[truncated]"


# ===========================================================================
# 5. SQLITE CRUD — stateful tool backed by a file DB
# ===========================================================================

DB_PATH = SANDBOX / "notes.db"


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY, text TEXT)")
    return conn


@mcp.tool()
def note_add(text: str) -> int:
    """Add a note, returns its id."""
    with _db() as c:
        cur = c.execute("INSERT INTO notes(text) VALUES (?)", (text,))
        return cur.lastrowid


@mcp.tool()
def note_list() -> list[dict]:
    """List all notes."""
    with _db() as c:
        return [{"id": i, "text": t} for i, t in c.execute("SELECT id, text FROM notes")]


@mcp.tool()
def note_update(note_id: int, text: str) -> str:
    """Update a note by id."""
    with _db() as c:
        c.execute("UPDATE notes SET text=? WHERE id=?", (text, note_id))
    return f"Updated note {note_id}"


@mcp.tool()
def note_delete(note_id: int) -> str:
    """Delete a note by id."""
    with _db() as c:
        c.execute("DELETE FROM notes WHERE id=?", (note_id,))
    return f"Deleted note {note_id}"


# ===========================================================================
# 6. SHELL RUNNER — dangerous by nature, so we use an allowlist
# ===========================================================================

ALLOWED_COMMANDS = {"ls", "pwd", "echo", "date", "whoami", "uname"}


@mcp.tool()
def run_command(command: str) -> str:
    """Run a shell command. Only the first token is checked against an allowlist.
    Students should notice: arbitrary shell access is a footgun — restrict it.
    """
    first = command.strip().split(" ", 1)[0]
    if first not in ALLOWED_COMMANDS:
        raise ValueError(f"'{first}' is not in the allowlist {sorted(ALLOWED_COMMANDS)}")
    out = subprocess.run(
        command, shell=True, capture_output=True, text=True, timeout=5, cwd=SANDBOX
    )
    return out.stdout + (f"\n[stderr]\n{out.stderr}" if out.stderr else "")


# ===========================================================================
# 7. GUI AUTOMATION — cross-platform via pyautogui
# ===========================================================================

@mcp.tool()
def screen_size() -> dict:
    """Return the primary screen size — a harmless GUI sanity check."""
    import pyautogui  # imported lazily so headless CI doesn't break
    w, h = pyautogui.size()
    return {"width": w, "height": h}


@mcp.tool()
def move_mouse(x: int, y: int, duration: float = 0.3) -> str:
    """Move the mouse to absolute screen coordinates."""
    import pyautogui
    pyautogui.moveTo(x, y, duration=duration)
    return f"Moved to ({x}, {y})"


@mcp.tool()
def type_text(text: str, interval: float = 0.02) -> str:
    """Type text into whichever window currently has focus."""
    import pyautogui
    pyautogui.typewrite(text, interval=interval)
    return f"Typed {len(text)} chars"


@mcp.tool()
def screenshot(path: str = "screenshot.png") -> str:
    """Save a screenshot into the sandbox."""
    import pyautogui
    p = _safe_path(path)
    pyautogui.screenshot(str(p))
    return f"Saved {path}"


# ===========================================================================
# 8. IMAGE TOOL — returns a real PNG (the old example returned raw bytes)
# ===========================================================================

@mcp.tool()
def create_thumbnail(image_path: str) -> Image:
    """Create a 100x100 PNG thumbnail from an image in the sandbox."""
    img = PILImage.open(_safe_path(image_path))
    img.thumbnail((100, 100))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Image(data=buf.getvalue(), format="png")


# ===========================================================================
# 9. PROMPTS — reusable templates the client can surface to users
# ===========================================================================

@mcp.prompt()
def review_code(code: str) -> str:
    """Ask the model to review a block of code."""
    return f"Please review this code and point out bugs, smells, and fixes:\n\n{code}"


@mcp.prompt()
def debug_error(error: str) -> str:
    """Kick off a debugging conversation for an error message."""
    return (
        f"I'm seeing this error:\n\n{error}\n\n"
        "Help me debug it — start by asking what I've already tried."
    )


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"STARTING — sandbox at {SANDBOX}", file=sys.stderr)
    if len(sys.argv) > 1 and sys.argv[1] == "dev":
        mcp.run()
    else:
        mcp.run(transport="stdio")
