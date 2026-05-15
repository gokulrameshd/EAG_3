# EAG_3 — Agentic MCP + Camera Optics + Prefab UI

TSAI EAG 3 assignment: an MCP server with machine-vision calculator tools, an agent loop (Gemini) that calls those tools, and a live Prefab dashboard that shows inputs and results in the browser.

## Project layout

| File | Role |
|------|------|
| `example_mcp_server.py` | MCP server (tools, sandbox files, optics calculators, etc.) |
| `AgenticMCPUse.py` | Agent loop: Gemini → `FUNCTION_CALL` → MCP tools → `FINAL_ANSWER` |
| `camera_dashboard.py` | Builds `generated_app.py` and runs `prefab serve` after optics tool calls |
| `generated_app.py` | Auto-generated Prefab UI (do not edit by hand while the agent runs) |
| `prefab_server.log` | Prefab subprocess logs |
| `sandbox/` | Sandboxed directory for file CRUD tools |

## Setup

From this directory:

```bash
# Use the course venv or create your own
pip install "mcp[cli]" google-genai python-dotenv prefab-ui pillow requests pyautogui
```

Create `.env` in this folder:

```env
GEMINI_API_KEY=your_key_here
```

Confirm the Prefab CLI is available:

```bash
prefab --version
```

## Optics MCP tools

Defined in `example_mcp_server.py`:

### `calculate_sensor_and_focal_length`

Given horizontal **FOV** (°), **working distance** (mm), **min pixels** across the smallest feature, and **min feature size** (mm), returns suggested sensor resolution, focal length, and related metrics.

Optional: `pixel_pitch_um` (default 3.45), `aspect_ratio` (default 4:3).

### `calculate_pixels_per_mm`

Given **working distance**, **sensor horizontal pixels**, **focal length**, and optionally **FOV** or **pixel pitch**, returns spatial resolution on the object plane (pixels/mm).

## Run the agent + live UI

```bash
cd EAG_V3_assignments/EAG_3
python AgenticMCPUse.py
```

1. The script starts **Prefab** and prints: `http://127.0.0.1:5175`
2. Open that URL in a browser.
3. The agent connects to `example_mcp_server.py` over stdio and runs a camera-sizing task (FOV 30°, WD 500 mm, 4 px on 0.5 mm feature).
4. After each optics tool call, the **Inputs** and **Results** tabs in the browser update automatically.

Stop with `Ctrl+C` (Prefab shuts down in a `finally` block).

## Run the MCP server alone

For MCP Inspector or other clients:

```bash
python example_mcp_server.py
# or
mcp dev example_mcp_server.py
```

If the inspector uses `uv` and you see `spawn uv ENOENT`, either install [uv](https://docs.astral.sh/uv/) or set the command to `python` with args `example_mcp_server.py`.

## Architecture

```
  AgenticMCPUse.py          example_mcp_server.py
        │                            │
        │  stdio MCP                   │  @mcp.tool()
        ├──────────────────────────────►  calculate_sensor_and_focal_length
        │                            │  calculate_pixels_per_mm
        │                            │
        │  parse JSON result           │
        ▼                            │
  camera_dashboard.py                │
        │  write generated_app.py      │
        │  prefab serve                │
        ▼                            │
  Browser @ :5175  ◄── Inputs / Results tabs
```

The LLM does not generate UI code. `camera_dashboard.py` maps tool arguments and return dicts to Prefab **stat** widgets (same pattern as Session 4 *talk-to-app*, but driven by tool results instead of an LLM spec).

## Customizing the task

Edit the `task` and `system_prompt` strings in `AgenticMCPUse.py` to change FOV, working distance, feature size, or which tools the agent must call.

## Troubleshooting

| Issue | What to try |
|-------|-------------|
| `ModuleNotFoundError: mcp` | Activate the venv and `pip install "mcp[cli]"` |
| Prefab page blank / error | Check `prefab_server.log`; ensure `prefab-ui` is installed |
| `GEMINI_API_KEY` missing | Add key to `.env` in this directory |
| Dashboard not updating | Tool name must be one of the optics tools; result must be JSON/dict text |
| Inspector `spawn uv ENOENT` | Install uv or use `python example_mcp_server.py` as the launch command |
