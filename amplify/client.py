"""Model client: one place that talks to Mistral, and one place that logs usage.

Design rules (AGENTS.md hard rules 1-2, docs/06):

* The API key is read from ``MISTRAL_API_KEY`` at call time. It is never logged, never
  written to disk, never echoed in an error message.
* Requests ask for ``json_schema`` structured output so malformed output is impossible by
  construction; the response is *still* validated against the local schema afterwards
  (defence in depth).
* A dry-run client replays committed fixtures and costs nothing.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .config import Budgets, Config
from .errors import ConfigError, PermanentError, TransientError
from .usage import append_usage, estimate_cost, usage_record

LOGGER = logging.getLogger("amplify.client")

MISTRAL_ENDPOINT = "https://api.mistral.ai/v1/chat/completions"
MAX_RESPONSE_BYTES = 2_000_000


@dataclass
class Completion:
    payload: dict[str, Any]
    prompt_tokens: int
    completion_tokens: int
    model: str
    mode: str


class SupportsCompletion(Protocol):
    mode: str

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        schema: dict[str, Any],
        schema_name: str,
        task_id: str,
        agent: str,
        week: str | None,
        max_tokens: int,
        attempt: int = 1,
    ) -> Completion: ...


class MistralClient:
    mode = "live"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        config: Config,
        usage_path: Path,
        budgets: Budgets | None = None,
        endpoint: str = MISTRAL_ENDPOINT,
        timeout: float = 120.0,
    ):
        self.api_key = api_key or os.environ.get("MISTRAL_API_KEY", "")
        if not self.api_key:
            raise ConfigError(
                "MISTRAL_API_KEY is not set. Live cycles require it; use --dry-run for a "
                "zero-cost rehearsal. Never commit the key (AGENTS.md rule 1)."
            )
        self.config = config
        self.usage_path = usage_path
        self.budgets = budgets or config.budgets
        self.endpoint = endpoint
        self.timeout = timeout

    # -- internals ---------------------------------------------------------
    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            detail = exc.read(2000).decode("utf-8", "replace") if exc.fp else ""
            # Never echo request headers; detail may contain provider text only.
            if exc.code in {408, 409, 429} or exc.code >= 500:
                raise TransientError(f"Mistral HTTP {exc.code}: {detail[:300]}") from exc
            raise PermanentError(f"Mistral HTTP {exc.code}: {detail[:300]}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise TransientError(f"Mistral connection problem: {exc}") from exc
        if len(raw) > MAX_RESPONSE_BYTES:
            raise PermanentError("Mistral response exceeded the size cap")
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise PermanentError(f"Mistral returned non-JSON: {exc}") from exc

    @staticmethod
    def _extract_content(response: dict[str, Any]) -> str:
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise PermanentError("Mistral response had no choices[0].message.content") from exc
        if isinstance(content, list):  # some models return content chunks
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        if not isinstance(content, str) or not content.strip():
            raise PermanentError("Mistral returned empty content")
        return content

    # -- public ------------------------------------------------------------
    def complete_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        schema: dict[str, Any],
        schema_name: str,
        task_id: str,
        agent: str,
        week: str | None,
        max_tokens: int,
        attempt: int = 1,
    ) -> Completion:
        if max_tokens > self.budgets.per_item_max_tokens:
            max_tokens = self.budgets.per_item_max_tokens
        model = self.config.model_for(agent)
        body = {
            "model": model,
            "temperature": 0.2,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(user_payload, ensure_ascii=False, sort_keys=True),
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "schema": schema, "strict": True},
            },
        }
        response = self._post(body)
        content = self._extract_content(response)
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise TransientError(f"model output was not JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise TransientError("model output JSON was not an object")

        usage = response.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        total = prompt_tokens + completion_tokens
        if total > self.budgets.per_item_max_tokens:
            LOGGER.warning(
                "task %s exceeded per-item token cap: %s > %s",
                task_id, total, self.budgets.per_item_max_tokens,
            )
        record = usage_record(
            mode=self.mode,
            week=week,
            task_id=task_id,
            agent=agent,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_estimate_usd=estimate_cost(
                model, prompt_tokens, completion_tokens, self.config.pricing
            ),
            attempt=attempt,
        )
        append_usage(self.usage_path, record)
        LOGGER.info(
            "task=%s agent=%s model=%s tokens=%s", task_id, agent, model, record["total_tokens"]
        )
        return Completion(payload, prompt_tokens, completion_tokens, model, self.mode)


class DryRunClient:
    """Replays committed fixture outputs. Zero API cost, zero network."""

    mode = "dry_run"

    def __init__(self, fixtures_dir: Path, *, config: Config, usage_path: Path):
        self.fixtures_dir = fixtures_dir
        self.config = config
        self.usage_path = usage_path

    def complete_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        schema: dict[str, Any],
        schema_name: str,
        task_id: str,
        agent: str,
        week: str | None,
        max_tokens: int,
        attempt: int = 1,
    ) -> Completion:  # noqa: ARG002 - mirrored signature on purpose
        path = self.fixtures_dir / f"{task_id}.json"
        if not path.exists():
            raise PermanentError(
                f"dry-run fixture missing: {path.name}. Add a canned output to "
                f"{self.fixtures_dir} or run live with Samuel's authorisation."
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise PermanentError(f"dry-run fixture is not JSON: {path}: {exc}") from exc
        append_usage(
            self.usage_path,
            usage_record(
                mode="dry_run",
                week=week,
                task_id=task_id,
                agent=agent,
                model="dry-run",
                prompt_tokens=0,
                completion_tokens=0,
                cost_estimate_usd=0.0,
                attempt=attempt,
            ),
        )
        return Completion(payload, 0, 0, "dry-run", self.mode)
