"""Tests du client LLM : routage, repli, et chemin réseau OpenAI-compatible.

Le vrai code réseau (``_call_openai_compatible``) est exercé via
``httpx.MockTransport`` — aucune connexion réelle, pas de clé requise au-delà
d'une clé factice pour activer la branche réseau.
"""

import asyncio
import json

import httpx

from eu5_bot.config import Config
from eu5_bot.council.llm_client import LLMClient, extract_json


def _chat_completion(content: str) -> httpx.Response:
    return httpx.Response(
        200, json={"choices": [{"message": {"role": "assistant", "content": content}}]}
    )


def test_extract_json_variants():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json("```json\n{\"a\": {\"b\": 2}}\n```") == {"a": {"b": 2}}
    assert extract_json("<think>blah</think> texte {\"x\": 3} fin") == {"x": 3}


def test_no_key_falls_back_to_mock():
    client = LLMClient(Config())  # aucune clé
    data, raw, source = asyncio.run(
        client.complete_json("Trésorier", "cerebras", "qwen-3-32b", "sys", "usr")
    )
    assert source == "mock"
    assert "statut_financier" in data


def test_openai_compatible_network_path():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return _chat_completion('{"statut_financier": "FRAGILE", "confiance": 42}')

    config = Config(groq_api_key="test-key")
    client = LLMClient(config, transport=httpx.MockTransport(handler))
    data, raw, source = asyncio.run(
        client.complete_json("Trésorier", "groq", "llama-x", "système", "utilisateur")
    )
    assert source == "llm"
    assert data == {"statut_financier": "FRAGILE", "confiance": 42}
    assert "groq.com" in captured["url"]
    assert captured["auth"] == "Bearer test-key"
    assert captured["body"]["model"] == "llama-x"


def test_cerebras_falls_back_to_groq_when_only_groq_key():
    # Conseiller configuré sur Cerebras, mais seule la clé Groq est présente :
    # le routage doit basculer sur l'endpoint Groq.
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return _chat_completion('{"confiance": 1}')

    config = Config(groq_api_key="g")
    client = LLMClient(config, transport=httpx.MockTransport(handler))
    _, _, source = asyncio.run(
        client.complete_json("Trésorier", "cerebras", "qwen-3-32b", "s", "u")
    )
    assert source == "llm"
    assert "groq.com" in seen["url"]
