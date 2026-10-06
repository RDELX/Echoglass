"""Claude (Anthropic API) backend."""

import anthropic

from .base import ContextLine, Translator, llm_prompt


class ClaudeTranslator(Translator):
    def __init__(self, api_key: str | None, model: str = "claude-opus-5-5", effort: str = "low"):
        # api_key=None lets the SDK use ANTHROPIC_API_KEY or an `ant auth login` profile.
        self.client = anthropic.Anthropic(api_key=api_key, timeout=30.0)
        self.model = model
        self.effort = effort  # subtitles need speed; translation doesn't need deep thinking
        self.label = f"Claude ({model})"

    def translate(self, text: str, source: str | None, target: str,
                  context: list[ContextLine], kind: str = "speech") -> str:
        system, user = llm_prompt(text, source, target, context, kind)
        resp = self.client.beta.messages.create(
            model=self.model,
            max_tokens=2000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": self.effort},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if resp.stop_reason == "refusal":
            return ""
        return "".join(b.text for b in resp.content if b.type == "text").strip()
