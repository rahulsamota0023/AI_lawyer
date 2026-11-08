"""One thin, swappable LLM layer over plain HTTPS (no SDK lock-in).

Switch model with env vars / the sidebar:
    LLM_PROVIDER = gemini | anthropic | openai | mock | mock-trap
    LLM_MODEL    = (optional) overrides the default below
    GEMINI_API_KEY / ANTHROPIC_API_KEY / OPENAI_API_KEY
"""
import base64
import json
import os
import re
import time

import requests

DEFAULT_MODELS = {
    "gemini": "gemini-2.5-flash",       # free tier via Google AI Studio; change if Google retires the name
    "anthropic": "claude-sonnet-5-5",
    "openai": "gpt-4o-mini",
}
KEY_ENV = {"gemini": "GEMINI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}


class LLMError(Exception):
    pass


def strip_json(text: str):
    """Parse JSON from a model reply that may have ``` fences or chatter around it. Returns dict or None."""
    if not text:
        return None
    t = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(t)
    except Exception:
        m = re.search(r"\{.*\}", t, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None


class LLM:
    def __init__(self, provider=None, model=None, api_key=None):
        self.provider = (provider or os.getenv("LLM_PROVIDER") or "mock").lower()
        self.model = model or os.getenv("LLM_MODEL") or DEFAULT_MODELS.get(self.provider, "")
        self.api_key = api_key or os.getenv(KEY_ENV.get(self.provider, ""), "")
        self.calls = 0
        if self.provider.startswith("mock"):
            from .mock import MockLLM
            self._mock = MockLLM(trap=self.provider == "mock-trap")

    @property
    def is_mock(self):
        return self.provider.startswith("mock")

    def chat(self, system, messages, json_mode=False, temperature=0.2, max_tokens=900):
        """messages = [{'role': 'user'|'assistant', 'content': str}]. Returns text."""
        self.calls += 1
        if self.is_mock:
            return self._mock.chat(system, messages, json_mode)
        if not self.api_key:
            raise LLMError(f"No API key for '{self.provider}'. Set {KEY_ENV.get(self.provider)} or paste a key in the sidebar.")
        for attempt in range(3):
            try:
                return getattr(self, f"_{self.provider}")(system, messages, json_mode, temperature, max_tokens)
            except LLMError as e:
                if "429" in str(e) and attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise
        raise LLMError("unreachable")

    # ---- providers
    def _post(self, url, headers, body):
        try:
            r = requests.post(url, headers=headers, json=body, timeout=60)
        except requests.RequestException as e:
            raise LLMError(f"Network error: {e}")
        if r.status_code == 429:
            raise LLMError("429: free-tier quota reached. Wait a minute, or paste your own key in the sidebar.")
        if r.status_code >= 400:
            raise LLMError(f"{r.status_code}: {r.text[:300]}")
        return r.json()

    def _gemini(self, system, messages, json_mode, temperature, max_tokens):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m["content"]}]} for m in messages],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens,
                                 **({"responseMimeType": "application/json"} if json_mode else {})},
        }
        data = self._post(url, {"x-goog-api-key": self.api_key}, body)
        try:
            return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError):
            raise LLMError(f"Unexpected Gemini response: {str(data)[:300]}")

    def _anthropic(self, system, messages, json_mode, temperature, max_tokens):
        body = {"model": self.model, "max_tokens": max_tokens, "temperature": temperature, "system": system, "messages": messages}
        data = self._post("https://api.anthropic.com/v1/messages",
                          {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}, body)
        return "".join(b.get("text", "") for b in data.get("content", []))

    def _openai(self, system, messages, json_mode, temperature, max_tokens):
        body = {"model": self.model, "temperature": temperature, "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}] + messages}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        data = self._post("https://api.openai.com/v1/chat/completions", {"Authorization": f"Bearer {self.api_key}"}, body)
        return data["choices"][0]["message"]["content"]

    # ---- voice (Gemini only; untested in the submitted build)
    def transcribe(self, audio_bytes: bytes, mime="audio/wav"):
        if self.provider != "gemini" or not self.api_key:
            raise LLMError("Voice input needs the Gemini provider and a key.")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        body = {"contents": [{"role": "user", "parts": [
            {"text": "Transcribe this audio exactly, in the language and script spoken (Hindi in Devanagari). Output only the transcript."},
            {"inlineData": {"mimeType": mime, "data": base64.b64encode(audio_bytes).decode()}}]}]}
        data = self._post(url, {"x-goog-api-key": self.api_key}, body)
        return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"]).strip()
