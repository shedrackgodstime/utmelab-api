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
        is_vision = bool(image_path and image_path.exists())
        if model_override:
            candidates = [model_override]
        elif is_vision:
            candidates = [self.vision_model, "openrouter/openrouter/free", "opencode/muse-spark-1.3-contributor-free"]
        else:
            candidates = [self.text_model, "openrouter/openrouter/free", "opencode/space-bunny-free"]

        # Deduplicate candidates while preserving priority order
        deduped = []
        for c in candidates:
            if c not in deduped:
                deduped.append(c)

        last_error = None
        for model in deduped:
            cmd = ["opencode", "run", "-m", model]
            if is_vision:
                cmd.extend(["-f", str(image_path)])

            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(input=prompt.encode("utf-8")),
                    timeout=self.timeout,
                )
                if proc.returncode == 0:
                    return stdout_bytes.decode("utf-8", errors="replace")

                err_msg = stderr_bytes.decode("utf-8", errors="replace")
                last_error = RuntimeError(f"OpenCode {model} failed (exit code {proc.returncode}): {err_msg}")
            except Exception as e:
                last_error = e

        if last_error:
            raise last_error
        raise RuntimeError("No candidate models succeeded")
