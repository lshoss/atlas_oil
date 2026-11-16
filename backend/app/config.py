from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, extra="ignore")

    # --- IBM watsonx Orchestrate ---
    # URL da instância (a mesma usada em `orchestrate env add`) e UUID do agente implantado.
    watsonx_orchestrate_service_url: str = ""
    watsonx_orchestrate_agent_id: str = ""
    # Em IBM Cloud, a API key é trocada por um token IAM no backend. Para outros ambientes,
    # um bearer token pode ser informado diretamente (ele expira e deve ser rotacionado).
    watsonx_orchestrate_api_key: str = ""
    watsonx_orchestrate_access_token: str = ""
    watsonx_orchestrate_iam_url: str = "https://iam.cloud.ibm.com/identity/token"

    # Chave que protege os endpoints OpenAPI chamados pelas ferramentas do Orchestrate.
    atlasoil_tool_api_key: str = ""

    # Orchestrate é o principal. Groq só é usado quando selecionado explicitamente.
    llm_provider: Literal["watsonx_orchestrate", "groq"] = "watsonx_orchestrate"

    # --- GroqCloud (API compatível com OpenAI) ---
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-20b"
    groq_base_url: str = "https://api.groq.com/openai/v1"

    # --- Outros ---
    finnhub_api_key: str = ""
    extra_assets: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
