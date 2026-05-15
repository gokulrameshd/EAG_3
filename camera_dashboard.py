"""
Build and serve a Prefab dashboard for camera / optics MCP tool runs.

Used by AgenticMCPUse.py: after each optics tool call, we write generated_app.py
and restart `prefab serve` so the browser shows inputs and calculated values.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

HERE = Path(__file__).parent
GENERATED = HERE / "generated_app.py"

CAMERA_TOOLS = frozenset({
    "calculate_sensor_and_focal_length",
    "calculate_pixels_per_mm",
})

INPUT_LABELS = {
    "fov_deg": "FOV (degrees)",
    "working_distance_mm": "Working distance (mm)",
    "min_pixels": "Min pixels per feature",
    "min_feature_size_mm": "Min feature size (mm)",
    "pixel_pitch_um": "Pixel pitch (µm)",
    "aspect_ratio": "Aspect ratio (W/H)",
    "sensor_horizontal_pixels": "Sensor width (px)",
    "sensor_vertical_pixels": "Sensor height (px)",
    "focal_length_mm": "Focal length (mm)",
}

RESULT_LABELS = {
    "horizontal_pixels": "Horizontal resolution (px)",
    "vertical_pixels": "Vertical resolution (px)",
    "focal_length_mm": "Focal length (mm)",
    "sensor_width_mm": "Sensor width (mm)",
    "sensor_height_mm": "Sensor height (mm)",
    "object_fov_width_mm": "Object FOV width (mm)",
    "pixels_per_mm_on_object": "Pixels / mm (object)",
    "pixels_per_mm_horizontal": "Pixels / mm (horizontal)",
    "mm_per_pixel_horizontal": "Mm / pixel (horizontal)",
    "pixels_per_mm_vertical": "Pixels / mm (vertical)",
    "mm_per_pixel_vertical": "Mm / pixel (vertical)",
    "object_fov_height_mm": "Object FOV height (mm)",
    "sensor_width_mm": "Sensor width (mm)",
    "pixel_pitch_um": "Pixel pitch (µm)",
    "aspect_ratio": "Aspect ratio",
}


def _slug(s: str, default: str = "k") -> str:
    out = re.sub(r"[^a-zA-Z0-9_]+", "_", str(s)).strip("_").lower()
    return out or default


def _stat(label: str, value: object, sub: str = "") -> dict:
    w: dict = {"kind": "stat", "label": label, "value": str(value)}
    if sub:
        w["sub"] = sub
    return w


def _format_key(key: str) -> str:
    return INPUT_LABELS.get(key) or RESULT_LABELS.get(key) or key.replace("_", " ").title()


def build_camera_dashboard_spec(
    tool_name: str,
    arguments: dict,
    results: dict,
    step_note: str = "",
) -> dict:
    """Dashboard spec: Inputs tab + Results tab for one tool invocation."""
    input_widgets = [
        _stat(_format_key(k), v) for k, v in arguments.items() if v is not None
    ]
    result_widgets = [
        _stat(_format_key(k), v) for k, v in results.items()
    ]
    if not result_widgets:
        result_widgets = [{"kind": "text", "heading": "No results", "body": "Tool returned empty data."}]

    header = []
    if step_note:
        header.append({"kind": "text", "heading": "Latest step", "body": step_note, "level": "h3"})
    header.append(
        {
            "kind": "text",
            "heading": tool_name.replace("_", " ").title(),
            "body": "Values update after each optics MCP tool call.",
            "level": "h2",
        }
    )

    return {
        "template": "dashboard",
        "params": {
            "title": "Camera & Lens Calculator",
            "tabs": [
                {
                    "name": "Inputs",
                    "widgets": header + input_widgets,
                },
                {
                    "name": "Results",
                    "widgets": result_widgets,
                },
            ],
        },
    }


def widget_lines(w: dict, ctx: dict) -> list[str]:
    kind = w.get("kind", "")
    ctx["uid"] = ctx.get("uid", 0) + 1

    if kind == "stat":
        label = w.get("label", "")
        value = str(w.get("value", ""))
        sub = w.get("sub", "")
        out = ["with Column(gap=1):", f"    Muted({label!r})", f"    H1({value!r})"]
        if sub:
            out.append(f"    Muted({sub!r})")
        return out

    if kind == "text":
        heading = w.get("heading", "")
        body = w.get("body", "")
        level = str(w.get("level", "h3")).lower()
        out = ["with Column(gap=1):"]
        if heading:
            tag = "H1" if level == "h1" else "H2" if level == "h2" else "H3"
            out.append(f"    {tag}({heading!r})")
        if body:
            out.append(f"    Muted({body!r})")
        return out

    return [f'Muted("Unknown widget: {kind!r}")']


def dashboard(title: str, tabs: list[dict]) -> str:
    if not tabs:
        tabs = [{"name": "Main", "widgets": [{"kind": "text", "heading": "Empty"}]}]

    ctx: dict = {"uid": 0}
    tab_indent = " " * 24
    built_tabs: list[tuple[str, str, str]] = []

    for i, tab in enumerate(tabs):
        name = str(tab.get("name") or f"Tab {i + 1}")
        value = _slug(tab.get("value") or name, f"tab_{i + 1}")
        widgets = tab.get("widgets") or []
        body_lines: list[str] = []
        if not widgets:
            body_lines = [tab_indent + 'Muted("(empty)")']
        else:
            for w in widgets:
                for line in widget_lines(w, ctx):
                    body_lines.append((tab_indent + line) if line else "")
        built_tabs.append((name, value, "\n".join(body_lines)))

    first_value = built_tabs[0][1]
    parts = [
        "from prefab_ui.app import PrefabApp",
        "from prefab_ui.components import (",
        "    Card, CardContent, CardHeader, CardTitle,",
        "    Column, H1, H2, H3, Muted, Tab, Tabs, Text,",
        ")",
        "",
        'with PrefabApp(css_class="max-w-5xl mx-auto p-6") as app:',
        "    with Card():",
        "        with CardHeader():",
        f"            CardTitle({title!r})",
        "        with CardContent():",
        f"            with Tabs(value={first_value!r}):",
    ]
    for name, value, body in built_tabs:
        parts.append(f'                with Tab({name!r}, value={value!r}):')
        parts.append("                    with Column(gap=5):")
        parts.append(body)
    return "\n".join(parts) + "\n"


TEMPLATES = {"dashboard": dashboard}


def write_app(spec: dict) -> None:
    name = spec.get("template", "dashboard")
    params = spec.get("params", {})
    if name not in TEMPLATES:
        raise ValueError(f"Unknown template {name!r}")
    source = TEMPLATES[name](**params)
    compile(source, "<generated_app>", "exec")
    GENERATED.write_text(source, encoding="utf-8")
    os.utime(GENERATED, None)


def write_waiting_app() -> None:
    spec = {
        "template": "dashboard",
        "params": {
            "title": "Camera & Lens Calculator",
            "tabs": [
                {
                    "name": "Status",
                    "widgets": [
                        {
                            "kind": "text",
                            "heading": "Waiting for agent",
                            "body": (
                                "Run AgenticMCPUse.py and open http://127.0.0.1:5175. "
                                "Inputs and results appear here after each optics tool call."
                            ),
                            "level": "h2",
                        },
                    ],
                },
            ],
        },
    }
    write_app(spec)


def parse_tool_result(payload: str) -> dict | None:
    """Parse MCP tool text payload into a dict."""
    payload = payload.strip()
    if not payload or payload.startswith("ERROR:"):
        return None
    try:
        data = json.loads(payload)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    try:
        import ast

        data = ast.literal_eval(payload)
        return data if isinstance(data, dict) else None
    except (ValueError, SyntaxError):
        return None


class PrefabServer:
    def __init__(self, target: Path, log_path: Path):
        self.target = target
        self.log_path = log_path
        self._proc: subprocess.Popen | None = None
        self._log = None

    def start(self) -> None:
        self._log = open(self.log_path, "a", encoding="utf-8")
        self._log.write("\n===== restart =====\n")
        self._log.flush()
        self._proc = subprocess.Popen(
            ["prefab", "serve", str(self.target)],
            cwd=self.target.parent,
            stdout=self._log,
            stderr=subprocess.STDOUT,
        )

    def stop(self) -> None:
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
            self._proc = None
        if self._log is not None:
            self._log.close()
            self._log = None

    def restart(self) -> None:
        self.stop()
        self.start()

    def refresh_dashboard(
        self,
        tool_name: str,
        arguments: dict,
        results: dict,
        step_note: str = "",
    ) -> None:
        spec = build_camera_dashboard_spec(tool_name, arguments, results, step_note)
        write_app(spec)
        self.restart()
        time.sleep(1.0)


def start_prefab_server() -> PrefabServer:
    log_path = HERE / "prefab_server.log"
    write_waiting_app()
    server = PrefabServer(GENERATED, log_path)
    server.start()
    time.sleep(1.5)
    return server
