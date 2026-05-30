from cerberus_proxy.adapters.anthropic_adapter import AnthropicAdapter
from cerberus_proxy.adapters.base import AdapterConfig, LLMAdapter
from cerberus_proxy.adapters.mistral_adapter import MistralAdapter
from cerberus_proxy.adapters.ollama_adapter import OllamaAdapter
from cerberus_proxy.adapters.openai_adapter import OpenAIAdapter

PROVIDER_MAP: dict[str, type[LLMAdapter]] = {
    "openai": OpenAIAdapter,
    "anthropic": AnthropicAdapter,
    "ollama": OllamaAdapter,
    "mistral": MistralAdapter,
    "grok": OpenAIAdapter,
    "nvidia": OpenAIAdapter,
}


def get_adapter(provider: str, config: AdapterConfig) -> LLMAdapter:
    cls = PROVIDER_MAP.get(provider.lower())
    if not cls:
        raise ValueError(f"Unknown provider: {provider}")
    return cls(config)
