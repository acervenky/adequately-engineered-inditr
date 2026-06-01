"""
LLM configuration for IndITR — Bring Your Own LLM.

Uses LiteLLM as the provider abstraction layer so any OpenAI-compatible
endpoint works without code changes — just set env vars.

PROVIDERS (examples):
  Ollama (local):
      LLM_BASE_URL=http://localhost:11434/v1
      LLM_API_KEY=ollama
      LLM_MODEL=ollama/qwen2.5:latest

  LM Studio (local):
      LLM_BASE_URL=http://localhost:1234/v1
      LLM_API_KEY=lm-studio
      LLM_MODEL=lm_studio/your-model-name

  vLLM (local / self-hosted):
      LLM_BASE_URL=http://localhost:8001/v1
      LLM_API_KEY=vllm
      LLM_MODEL=openai/mistral-7b-instruct

  DeepInfra (cloud):
      LLM_BASE_URL=https://api.deepinfra.com/v1/openai
      LLM_API_KEY=<your-deepinfra-key>
      LLM_MODEL=deepinfra/nvidia/NVIDIA-Nemotron-3-Super-120B-A12B

  OpenAI:
      LLM_BASE_URL=https://api.openai.com/v1
      LLM_API_KEY=<your-openai-key>
      LLM_MODEL=openai/gpt-4o-mini

NO LLM calls in: engine/, output_builders/
Embeddings use BGE-small-en-v1.5 (sentence-transformers) — no LLM needed.
"""
import os
import litellm
from dotenv import load_dotenv

load_dotenv()

# Text model — change to any model your endpoint serves
MODEL        = os.getenv("LLM_MODEL",        "ollama/qwen2.5:latest")
VISION_MODEL = os.getenv("LLM_VISION_MODEL", "ollama/llava:latest")

litellm.api_key = os.getenv("LLM_API_KEY", "ollama")

# api_base is only set for providers that need an explicit endpoint.
# OpenRouter-prefixed models ("openrouter/...") are routed by LiteLLM natively
# — setting api_base would override that routing and break the call.
_base_url = os.getenv("LLM_BASE_URL", "")
_is_native = MODEL.startswith(("openrouter/", "anthropic/", "cohere/", "huggingface/"))
if _base_url and not _is_native:
    litellm.api_base = _base_url
elif not _base_url and not _is_native:
    litellm.api_base = "http://localhost:11434/v1"   # default: local Ollama

# OpenRouter: expose key under the name LiteLLM also checks automatically
if MODEL.startswith("openrouter/") and not os.getenv("OPENROUTER_API_KEY"):
    os.environ["OPENROUTER_API_KEY"] = litellm.api_key  # type: ignore[arg-type]

# --- Legacy DeepInfra env vars still work (backwards compat) ---
if os.getenv("DEEPINFRA_API_KEY") and not os.getenv("LLM_API_KEY"):
    litellm.api_key  = os.getenv("DEEPINFRA_API_KEY", "")
    litellm.api_base = os.getenv("LITELLM_API_BASE", "https://api.deepinfra.com/v1/openai")
    MODEL            = os.getenv("LITELLM_MODEL", MODEL)
    VISION_MODEL     = os.getenv("LITELLM_VISION_MODEL", VISION_MODEL)

# Request timeout — critical for local models which may be slow to respond.
# BYOLLM users can raise this if their hardware is slow.
litellm.request_timeout = int(os.getenv("LLM_TIMEOUT_SECONDS", "120"))
