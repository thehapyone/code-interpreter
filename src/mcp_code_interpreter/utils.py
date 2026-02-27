"""Utility functions for code execution and output formatting."""

import json
from collections.abc import AsyncIterator
from typing import Any

from jupyter_client import KernelManager


def format_jupyter_outputs(outputs: list[dict[str, Any]]) -> dict[str, Any]:
    """Format Jupyter outputs into text and plots"""
    text_parts = []
    plots = []

    for output in outputs:
        if output["type"] == "stream":
            text_parts.append(output["text"])

        elif output["type"] == "execute_result":
            data = output["data"]
            if "text/plain" in data:
                text_parts.append(data["text/plain"])
            if "image/png" in data:
                plots.append({"format": "png", "data": data["image/png"]})

        elif output["type"] == "display_data":
            data = output["data"]
            if "image/png" in data:
                plots.append({"format": "png", "data": data["image/png"]})
            if "text/html" in data:
                text_parts.append(f"[HTML Output]\n{data['text/html'][:200]}...")

        elif output["type"] == "error":
            text_parts.append("\n".join(output["traceback"]))

    return {"text": "\n".join(text_parts), "plots": plots if plots else None}


def execute_code_jupyter(km: KernelManager, code: str, timeout: int = 300) -> dict[str, Any]:
    """Execute code using Jupyter kernel"""
    kc = km.client()

    try:
        kc.start_channels()
        kc.wait_for_ready(timeout=30)

        # Execute code
        kc.execute(code)

        outputs = []
        execution_count = None
        status = "success"
        error_message = None

        # Collect all outputs
        while True:
            try:
                msg = kc.get_iopub_msg(timeout=timeout)
                msg_type = msg["header"]["msg_type"]
                content = msg["content"]

                if msg_type == "execute_input":
                    execution_count = content.get("execution_count")

                elif msg_type == "stream":
                    outputs.append(
                        {"type": "stream", "name": content["name"], "text": content["text"]}
                    )

                elif msg_type == "execute_result":
                    outputs.append(
                        {
                            "type": "execute_result",
                            "data": content["data"],
                            "execution_count": content.get("execution_count"),
                        }
                    )

                elif msg_type == "display_data":
                    outputs.append({"type": "display_data", "data": content["data"]})

                elif msg_type == "error":
                    status = "error"
                    error_message = "\n".join(content["traceback"])
                    outputs.append(
                        {
                            "type": "error",
                            "ename": content["ename"],
                            "evalue": content["evalue"],
                            "traceback": content["traceback"],
                        }
                    )

                elif msg_type == "status" and content["execution_state"] == "idle":
                    break

            except Exception as e:
                if "Empty message" in str(e) or "Timeout" in str(e):
                    break
                raise

        kc.stop_channels()

        # Format output
        formatted_output = format_jupyter_outputs(outputs)

        return {
            "status": status,
            "output": formatted_output["text"],
            "outputs": outputs,
            "execution_count": execution_count,
            "error": error_message,
            "plots": formatted_output.get("plots"),
        }

    except Exception as e:
        kc.stop_channels()
        return {
            "status": "error",
            "error": str(e),
            "output": "",
        }


async def execute_code_streaming(
    km: KernelManager, code: str, timeout: int = 300
) -> AsyncIterator[str]:
    """Execute code with streaming output."""
    kc = km.client()

    try:
        kc.start_channels()
        kc.wait_for_ready(timeout=30)

        kc.execute(code)

        while True:
            try:
                msg = kc.get_iopub_msg(timeout=1)
                msg_type = msg["header"]["msg_type"]
                content = msg["content"]

                if msg_type == "stream":
                    yield f"data: {json.dumps({'type': 'stream', 'text': content['text']})}\n\n"

                elif msg_type == "execute_result":
                    yield f"data: {json.dumps({'type': 'result', 'data': content['data']})}\n\n"

                elif msg_type == "display_data":
                    yield f"data: {json.dumps({'type': 'display', 'data': content['data']})}\n\n"

                elif msg_type == "error":
                    yield f"data: {json.dumps({'type': 'error', 'traceback': content['traceback']})}\n\n"

                elif msg_type == "status" and content["execution_state"] == "idle":
                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
                    break

            except Exception:
                break

        kc.stop_channels()

    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
