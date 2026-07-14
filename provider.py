"""
ZenProvider — OpenAI-compatible chat completions via OpenCode Zen.
"""

import time

import requests


class ZenProvider:
    """Minimal OpenAI-compatible provider targeting OpenCode Zen."""

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://opencode.ai/zen/v1",
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")

    def chat(
        self,
        messages: list,
        tools: list | None = None,
        tool_choice: str = "auto",
        max_tokens: int = 2000,
        temperature: float = 0.4,
        max_retries: int = 5,
    ) -> dict:
        """
        Send a chat completion request with retry on 429 rate limits.

        Returns response["choices"][0]["message"] dict, which may contain
        "content" (str | None) and/or "tool_calls" (list).
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens or 16384,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice

        last_error = None
        for attempt in range(max_retries):
            try:
                resp = requests.post(
                    f"{self.base_url}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=120,
                )
            except requests.exceptions.Timeout as exc:
                wait = min(2 ** attempt + 1, 60)
                print(f"  Request timed out, retrying in {wait}s... (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait)
                last_error = exc
                continue
            except requests.exceptions.ConnectionError as exc:
                wait = min(2 ** attempt + 1, 60)
                print(f"  Connection error, retrying in {wait}s... (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait)
                last_error = exc
                continue
            except requests.exceptions.RequestException as exc:
                # Catch-all for other request failures
                wait = min(2 ** attempt + 1, 60)
                print(f"  Request failed ({exc}), retrying in {wait}s... (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait)
                last_error = exc
                continue
            if resp.status_code == 429:
                wait = min(2 ** attempt + 1, 60)
                print(f"  Rate limited (429), retrying in {wait}s... (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait)
                last_error = resp
                continue
            if 500 <= resp.status_code < 600:
                wait = min(2 ** attempt + 1, 60)
                print(f"  Server error ({resp.status_code}), retrying in {wait}s... (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait)
                last_error = resp
                continue
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]

        last_status = getattr(last_error, 'status_code', None) if last_error else None
        raise requests.exceptions.HTTPError(
            f"Max retries ({max_retries}) exceeded. Last response: {last_status or last_error or 'N/A'}",
            response=last_error if isinstance(last_error, requests.Response) else None,
        )
