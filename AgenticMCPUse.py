"""
Agentic loop over example_mcp_server.py using Gemini.

The model picks tools from the MCP server and we execute them, feeding results
back into the prompt until it emits FINAL_ANSWER. Optics tool results are
mirrored to a Prefab dashboard in the browser (http://127.0.0.1:5175).

Run (from this directory):
  python AgenticMCPUse.py

Requires:
  GEMINI_API_KEY in .env
  pip install mcp google-genai python-dotenv prefab-ui
  prefab CLI on PATH (`pip install prefab-ui` usually provides it)
"""

from __future__ import annotations

import asyncio
import os
import sys
from concurrent.futures import TimeoutError
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from camera_dashboard import CAMERA_TOOLS, parse_tool_result, start_prefab_server

load_dotenv()

HERE = Path(__file__).parent
MODEL = "gemini-3.1-flash-lite-preview"
MAX_ITERATIONS = 8
LLM_SLEEP_SECONDS = 5
LLM_TIMEOUT = 30

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


async def generate_with_timeout(prompt: str, timeout: int = LLM_TIMEOUT):
    """Run the blocking Gemini call in a thread with a timeout."""
    loop = asyncio.get_event_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(
            None,
            lambda: client.models.generate_content(model=MODEL, contents=prompt),
        ),
        timeout=timeout,
    )


def describe_tools(tools) -> str:
    lines = []
    for i, t in enumerate(tools, 1):
        props = (t.inputSchema or {}).get("properties", {})
        params = ", ".join(f"{n}: {p.get('type', '?')}" for n, p in props.items()) or "no params"
        lines.append(f"{i}. {t.name}({params}) — {t.description or ''}")
    return "\n".join(lines)


def coerce(value: str, schema_type: str):
    if schema_type == "integer":
        return int(value)
    if schema_type == "number":
        return float(value)
    if schema_type == "array":
        return eval(value)  # teaching code; fine inside the sandbox
    if schema_type == "boolean":
        return value.lower() in ("true", "1", "yes")
    if schema_type == "null" and value.lower() in ("none", "null", ""):
        return None
    return value


async def main():
    prefab = start_prefab_server()
    print("Prefab UI: http://127.0.0.1:5175  (inputs/results update after optics tool calls)\n")

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[str(HERE / "example_mcp_server.py")],
        cwd=str(HERE),
    )

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                print("Connected to example_mcp_server")

                tools = (await session.list_tools()).tools
                tools_desc = describe_tools(tools)
                print(f"Loaded {len(tools)} tools\n")

                system_prompt = f"""You are a machine-vision sizing agent using MCP tools.
You solve tasks by calling tools ONE AT A TIME and observing their results.

Available tools:
{tools_desc}

Respond with EXACTLY ONE line, in one of these two formats:
  FUNCTION_CALL: tool_name|arg1|arg2|...
  FINAL_ANSWER: <short natural-language summary of what you calculated>

Rules:
- Provide args in the exact order of the tool's parameters.
- For optional parameters you may omit trailing args (defaults apply).
- Use calculate_sensor_and_focal_length first when both optics tools are needed.
- Then use calculate_pixels_per_mm with values from the first tool's result.
- Do not invent tools that are not listed above.
- When the task is complete, emit FINAL_ANSWER summarizing sensor size, focal length, and px/mm.
"""

                task = (
                    "Size a camera for this setup: horizontal FOV = 30 degrees, "
                    "working distance = 500 mm, need at least 4 pixels across a "
                    "0.5 mm feature (pixel pitch 3.45 µm). "
                    "First call calculate_sensor_and_focal_length with those values. "
                    "Then call calculate_pixels_per_mm using the horizontal resolution "
                    "and focal length from that result (same FOV and working distance). "
                    "Finish with FINAL_ANSWER."
                )

                history: list[str] = []
                for iteration in range(1, MAX_ITERATIONS + 1):
                    print(f"\n--- Iteration {iteration} ---")

                    context = "\n".join(history) if history else "(no prior steps)"
                    prompt = (
                        f"{system_prompt}\n"
                        f"Task: {task}\n\n"
                        f"Previous steps:\n{context}\n\n"
                        f"What is your next single action?"
                    )

                    print(f"Sleeping {LLM_SLEEP_SECONDS}s before LLM call...")
                    await asyncio.sleep(LLM_SLEEP_SECONDS)

                    try:
                        response = await generate_with_timeout(prompt)
                    except (TimeoutError, asyncio.TimeoutError):
                        print("LLM timed out — stopping.")
                        break
                    except Exception as e:
                        print(f"LLM error: {e}")
                        break

                    text = (response.text or "").strip().splitlines()[0].strip()
                    print(f"LLM: {text}")

                    if text.startswith("FINAL_ANSWER:"):
                        print("\n=== Agent done ===")
                        print(text)
                        break

                    if not text.startswith("FUNCTION_CALL:"):
                        print("Unexpected response format — stopping.")
                        break

                    _, call = text.split(":", 1)
                    parts = [p.strip() for p in call.split("|")]
                    func_name, raw_args = parts[0], parts[1:]

                    tool = next((t for t in tools if t.name == func_name), None)
                    if tool is None:
                        msg = f"Unknown tool {func_name!r}"
                        print(msg)
                        history.append(f"Iteration {iteration}: {msg}")
                        continue

                    props = (tool.inputSchema or {}).get("properties", {})
                    prop_items = list(props.items())
                    arguments = {}
                    for (name, info), val in zip(prop_items, raw_args):
                        if val == "":
                            continue
                        arguments[name] = coerce(val, info.get("type", "string"))

                    print(f"→ {func_name}({arguments})")
                    try:
                        result = await session.call_tool(func_name, arguments=arguments)
                        payload = (
                            result.content[0].text
                            if result.content and hasattr(result.content[0], "text")
                            else str(result)
                        )
                    except Exception as e:
                        payload = f"ERROR: {e}"

                    print(f"← {payload}")

                    if func_name in CAMERA_TOOLS:
                        parsed = parse_tool_result(payload)
                        if parsed:
                            try:
                                prefab.refresh_dashboard(
                                    func_name,
                                    arguments,
                                    parsed,
                                    step_note=f"Iteration {iteration}",
                                )
                                print("  → updated Prefab dashboard (browser)")
                            except Exception as e:
                                print(f"  → Prefab update failed: {e}")
                        else:
                            print("  → could not parse result for Prefab dashboard")

                    history.append(
                        f"Iteration {iteration}: called {func_name}({arguments}) → {payload}"
                    )
                else:
                    print("\nReached MAX_ITERATIONS without FINAL_ANSWER.")
    finally:
        print("\nShutting down Prefab server...")
        prefab.stop()


if __name__ == "__main__":
    asyncio.run(main())
