"""Screen analysis via Gemini Flash vision model."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from openai import AsyncOpenAI

from agents.hapax_voice.screen_models import Issue, ScreenAnalysis

log = logging.getLogger(__name__)

DEFAULT_CONTEXT_PATH = Path.home() / ".local" / "share" / "hapax-voice" / "screen_context.md"

_BASE_PROMPT = """\
You are a screen awareness system for a single-operator Linux workstation (Hyprland/Wayland).
Analyze the screenshot and return a JSON object with these fields:
- app: the active application name
- context: what the user is viewing/doing (1 sentence)
- summary: 2-3 sentence description of screen content
- issues: list of detected problems, each with severity ("error"/"warning"/"info"), description, confidence (0.0-1.0)
- suggestions: max 2 actionable suggestions, only if high confidence
- keywords: list of relevant terms for documentation lookup

Rules:
- Do NOT comment on non-work content (browsing, media, personal messages)
- Do NOT suggest unsolicited workflow changes
- Do NOT narrate obvious actions ("I see you opened a terminal")
- Focus on errors, failures, warnings, stack traces
- Use system knowledge below to make intelligent observations about service relationships

Return ONLY valid JSON, no markdown fences."""

_CONTEXT_HEADER = "\n\n## System Knowledge\n\n"


class ScreenAnalyzer:
    """Analyzes screenshots using Gemini Flash via LiteLLM."""

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

    async def analyze(
        self, image_base64: str, extra_context: str | None = None
    ) -> ScreenAnalysis | None:
        """Analyze a screenshot and return structured results."""
        try:
            return await self._call_vision(image_base64, extra_context)
        except Exception as exc:
            log.warning("Screen analysis failed: %s", exc)
            return None

    def _get_client(self) -> AsyncOpenAI:
        """Return a lazily-initialized AsyncOpenAI client."""
        if self._client is None:
            base_url = os.environ.get("LITELLM_BASE_URL", "http://127.0.0.1:4000")
            api_key = os.environ.get("LITELLM_API_KEY", "not-set")
            self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        return self._client

    async def _call_vision(
        self, image_base64: str, extra_context: str | None
    ) -> ScreenAnalysis | None:
        client = self._get_client()

        system = self._system_prompt
        if extra_context:
            system += "\n\n## Additional Context\n\n" + extra_context

        response = await client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{image_base64}",
                            },
                        },
                        {
                            "type": "text",
                            "text": "Analyze this screenshot.",
                        },
                    ],
                },
            ],
            temperature=0.1,
            max_tokens=1024,
        )

        raw = response.choices[0].message.content.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        data = json.loads(raw)
        return ScreenAnalysis(
            app=data.get("app", "unknown"),
            context=data.get("context", ""),
            summary=data.get("summary", ""),
            issues=[Issue(**i) for i in data.get("issues", [])],
            suggestions=data.get("suggestions", []),
            keywords=data.get("keywords", []),
        )
