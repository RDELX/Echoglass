"""OpenAI-compatible chat endpoint: Ollama, LM Studio, or OpenAI itself."""

import re

from openai import BadRequestError, OpenAI

from .base import ContextLine, Translator, llm_prompt

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


class OpenAICompatTranslator(Translator):
    def __init__(self, base_url: str | None, model: str, api_key: str | None = None,
                 label: str = "openai-compatible", reasoning_effort: str | None = None):
        # Local servers ignore the key but the client requires one.
        self.client = OpenAI(base_url=base_url, api_key=api_key or "not-needed", timeout=30)
        self.model = model
        # Reasoning models (e.g. Gemma 4 on Ollama) otherwise spend hundreds of tokens
        # thinking per line; "none" turns that off where the server supports it.
        self.reasoning_effort = reasoning_effort
        self.label = f"{label} ({model})"

    def translate(self, text: str, source: str | None, target: str,
                  context: list[ContextLine]) -> str:
        system, user = llm_prompt(text, source, target, context)
        kwargs = dict(
            model=self.model,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            temperature=0.2,
        )
        if self.reasoning_effort:
            try:
                resp = self.client.chat.completions.create(
                    reasoning_effort=self.reasoning_effort, **kwargs)
            except BadRequestError:
                self.reasoning_effort = None  # server/model doesn't accept it; stop sending
                resp = self.client.chat.completions.create(**kwargs)
        else:
            resp = self.client.chat.completions.create(**kwargs)
        out = resp.choices[0].message.content or ""
        return _THINK_RE.sub("", out).strip()
