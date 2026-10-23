"""Mock AI Client for ClaimCheck 2.0.

Intended Responsibility:
    Provides an offline, deterministic mock interface mimicking the OpenAI/Nebius
    LLM API responses for offline testing, local development, and CI environments
    where live Nebius API credits/keys are unavailable.

Expected Inputs:
    - messages: List of chat messages (role, content).
    - model: Name of target model (e.g. 'nvidia/nemotron-...').
    - temperature, response_format, max_tokens: Standard generation options.

Expected Outputs:
    - Structured mock completions with simulated reasoning tokens or JSON structures
      matching production schema expectations.

Status:
    Placeholder. No live remote network calls are executed in this phase.
"""

from typing import Any, Dict, Optional


class MockNebiusClient:
    """Mock client simulating Nebius Token Factory / OpenAI compatible API client."""

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = api_key or "mock-key-offline"
        self.base_url = base_url or "https://mock.local/v1"

    def chat_completion(
        self,
        messages: list,
        model: str = "mock-nemotron",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Generate a simulated mock response for offline verification."""
        return {
            "id": "mock-completion-001",
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "MOCK_RESPONSE: AI pipeline is in placeholder mode.",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 10,
                "total_tokens": 20,
            },
        }
