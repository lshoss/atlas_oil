"""Smoke test opt-in do agente AtlasOil implantado no watsonx Orchestrate.

Execute somente após configurar backend/.env e receber autorização para usar a instância:
    poetry run python -u integration_test.py

O script não imprime credenciais e não é executado pelo pytest.
"""

import asyncio
import json
import sys

from app.chat import ChatService
from app.config import Settings
from app.schemas import ChatMessage


async def main() -> int:
    settings = Settings()
    if settings.llm_provider != "watsonx_orchestrate":
        print("ERRO: defina LLM_PROVIDER=watsonx_orchestrate para este smoke test.")
        return 1
    required = {
        "WATSONX_ORCHESTRATE_SERVICE_URL": settings.watsonx_orchestrate_service_url,
        "WATSONX_ORCHESTRATE_AGENT_ID": settings.watsonx_orchestrate_agent_id,
    }
    missing = [name for name, value in required.items() if not value.strip()]
    if not (settings.watsonx_orchestrate_api_key or settings.watsonx_orchestrate_access_token):
        missing.append("WATSONX_ORCHESTRATE_API_KEY ou WATSONX_ORCHESTRATE_ACCESS_TOKEN")
    if missing:
        print(f"ERRO: configuração ausente: {', '.join(missing)}")
        return 1

    service = ChatService(
        settings.watsonx_orchestrate_api_key,
        "",
        settings.watsonx_orchestrate_service_url,
        provider="watsonx_orchestrate",
        agent_id=settings.watsonx_orchestrate_agent_id,
        access_token=settings.watsonx_orchestrate_access_token,
        iam_url=settings.watsonx_orchestrate_iam_url,
    )
    event_types: list[str] = []
    answer = ""
    try:
        async for frame in service.stream(
            [ChatMessage(role="user", content="Explique o Brent em uma frase, sem inventar preços.")]
        ):
            for line in frame.splitlines():
                if not line.startswith("data: "):
                    continue
                event = json.loads(line[6:])
                event_types.append(event["type"])
                answer += event.get("text", "")
    finally:
        await service.aclose()

    if "error" in event_types or "done" not in event_types or not answer.strip():
        print(f"FAIL — eventos recebidos: {event_types}")
        return 1
    print("PASS — agente respondeu pelo watsonx Orchestrate; credenciais ocultas.")
    print("Faça também um teste no chat IBM e confirme a execução de get_analysis.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
