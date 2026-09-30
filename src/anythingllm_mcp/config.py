"""Configuration for AnythingLLM MCP Server."""

import os

ANYTHINGLLM_BASE_URL = os.getenv(
    "ANYTHINGLLM_BASE_URL", "http://localhost:3001/api"
)
ANYTHINGLLM_API_KEY = os.getenv("ANYTHINGLLM_API_KEY", "")
