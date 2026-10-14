"""OpenCode CLI subprocess runner with stdin piping and multimodal image support."""

import asyncio
from pathlib import Path
from typing import Optional
from pipeline.config import config


class OpenCodeRunner:
    """Asynchronous wrapper around `opencode run` CLI."""

    def __init__(
        self,
        text_model: Optional[str] = None,
        vision_model: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        self.text_model = text_model or config.opencode_text_model
        self.vision_model = vision_model or config.opencode_vision_model
        self.timeout = timeout or config.ai_timeout_seconds

    async def complete(
        self,
        prompt: str,
        image_path: Optional[Path] = None,
        model_override: Optional[str] = None,
    ) -> str:
        """Executes opencode CLI with prompt over stdin and optional image attachment flag."""
        selected_model = model_override
        if not selected_model:
            selected_model = self.vision_model if (image_path and image_path.exists()) else self.text_model

        cmd = ["opencode", "run", "-m", selected_model]
        if image_path and image_path.exists():
            cmd.extend(["-f", str(image_path)])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=prompt.encode("utf-8")),
                timeout=self.timeout,
            )
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            raise TimeoutError(f"OpenCode process timed out after {self.timeout}s")

        if proc.returncode != 0:
            err_msg = stderr_bytes.decode("utf-8", errors="replace")
            raise RuntimeError(f"OpenCode execution failed (exit code {proc.returncode}): {err_msg}")

        return stdout_bytes.decode("utf-8", errors="replace")
