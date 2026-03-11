"""Workspace analysis via Gemini Flash vision model (multi-image)."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from openai import AsyncOpenAI

from agents.hapax_voice.screen_models import (
    GearObservation,
    Issue,
    WorkspaceAnalysis,
)

log = logging.getLogger(__name__)

DEFAULT_CONTEXT_PATH = Path.home() / ".local" / "share" / "hapax-voice" / "screen_context.md"

_BASE_PROMPT = """\
You are a workspace awareness system for a single-operator music production studio
(Linux/Hyprland/Wayland). You receive up to three images per analysis:

1. SCREENSHOT: The operator's primary monitor
2. OPERATOR CAMERA: Front-facing camera showing the operator at their desk
3. HARDWARE CAMERA: Camera facing the music production hardware rig

Return a JSON object with these fields:
- app: the active application name (from screenshot)
- context: what the user is viewing/doing (1 sentence)
- summary: 2-3 sentence description of workspace state
- issues: list of detected problems, each with severity ("error"/"warning"/"info"), description, confidence (0.0-1.0)
- suggestions: max 2 actionable suggestions, only if high confidence
- keywords: list of relevant terms for documentation lookup
- operator_present: boolean, is the operator visible (null if no operator camera)
- operator_activity: "typing", "using_hardware", "reading", "away", "unknown"
- operator_attention: "screen", "hardware", "away", "unknown"
- gear_state: list of observed hardware devices, each with device (name), powered (bool/null), display_content (str), notes (str)
- workspace_change: boolean, significant physical change from typical state

Rules:
- Do NOT comment on non-work content (browsing, media, personal messages)
- Do NOT suggest unsolicited workflow changes
- Do NOT narrate obvious actions
- Focus on errors, failures, warnings, stack traces in screenshots
- For gear_state, only report devices you can identify with reasonable confidence
- If a camera image is not provided, set corresponding fields to null/unknown
- The hardware rig includes: OXI One MKII, 2x SP-404 MKII, MPC Live III,
  Digitakt II, Digitone II, Analog Rytm MKII, and various effects pedals
- Use system knowledge below to make intelligent observations about service relationships

Return ONLY valid JSON, no markdown fences."""

_CONTEXT_HEADER = "\n\n## System Knowledge\n\n"


class WorkspaceAnalyzer:
    """Analyzes workspace state using Gemini Flash via LiteLLM (multi-image)."""

    def __init__(
        self,
        model: str = "gemini-flash",
        context_path: str | Path = DEFAULT_CONTEXT_PATH,
    ) -> None:
        self.model = model
        self._system_prompt = self._build_prompt(Path(context_path))
        self._client: AsyncOpenAI | None = None

    def _build_prompt(self, context_path: Path) -> str:
        prompt = _BASE_PROMPT
        try:
            if context_path.exists():
                context = context_path.read_text().strip()
                prompt += _CONTEXT_HEADER + context
                log.info("Loaded screen context from %s", context_path)
        except Exception as exc:
            log.warning("Failed to load screen context: %s", exc)
        return prompt

    def reload_context(self, context_path: Path | None = None) -> None:
        """Reload the static system context (e.g. after SIGHUP)."""
        path = context_path or DEFAULT_CONTEXT_PATH
        self._system_prompt = self._build_prompt(path)

    def _get_client(self) -> AsyncOpenAI:
        """Return a lazily-initialized AsyncOpenAI client."""
        if self._client is None:
            base_url = os.environ.get("LITELLM_BASE_URL", "http://127.0.0.1:4000")
            api_key = os.environ.get("LITELLM_API_KEY", "not-set")
            self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        return self._client

    async def analyze(
        self,
        screen_b64: str,
        operator_b64: str | None = None,
        hardware_b64: str | None = None,
        extra_context: str | None = None,
    ) -> WorkspaceAnalysis | None:
        """Analyze workspace from multiple image sources."""
        try:
            return await self._call_vision(
                screen_b64,
                operator_b64,
                hardware_b64,
                extra_context,
            )
        except Exception as exc:
            log.warning("Workspace analysis failed: %s", exc)
            return None

    def _build_messages(
        self,
        screen_b64: str,
        operator_b64: str | None,
        hardware_b64: str | None,
        extra_context: str | None,
    ) -> list[dict]:
        system = self._system_prompt
        if extra_context:
            system += "\n\n## Additional Context\n\n" + extra_context

        user_content: list[dict] = []

        # Screenshot (always present)
        user_content.append({"type": "text", "text": "SCREENSHOT:"})
        user_content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{screen_b64}"},
            }
        )

        # Operator camera (optional)
        if operator_b64:
            user_content.append({"type": "text", "text": "OPERATOR CAMERA:"})
            user_content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{operator_b64}"},
                }
            )

        # Hardware camera (optional)
        if hardware_b64:
            user_content.append({"type": "text", "text": "HARDWARE CAMERA:"})
            user_content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{hardware_b64}"},
                }
            )

        user_content.append(
            {
                "type": "text",
                "text": "Analyze this workspace.",
            }
        )

        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ]

    async def _call_vision(
        self,
        screen_b64: str,
        operator_b64: str | None,
        hardware_b64: str | None,
        extra_context: str | None,
    ) -> WorkspaceAnalysis | None:
        client = self._get_client()
        messages = self._build_messages(
            screen_b64,
            operator_b64,
            hardware_b64,
            extra_context,
        )

        response = await client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.1,
            max_tokens=4096,
        )

        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        data = json.loads(raw)

        gear_state = []
        for g in data.get("gear_state") or []:
            gear_state.append(
                GearObservation(
                    device=g.get("device", "unknown"),
                    powered=g.get("powered"),
                    display_content=g.get("display_content", ""),
                    notes=g.get("notes", ""),
                )
            )

        return WorkspaceAnalysis(
            app=data.get("app", "unknown"),
            context=data.get("context", ""),
            summary=data.get("summary", ""),
            issues=[Issue(**i) for i in data.get("issues", [])],
            suggestions=data.get("suggestions", []),
            keywords=data.get("keywords", []),
            operator_present=data.get("operator_present"),
            operator_activity=data.get("operator_activity", "unknown"),
            operator_attention=data.get("operator_attention", "unknown"),
            gear_state=gear_state,
            workspace_change=data.get("workspace_change", False),
        )
