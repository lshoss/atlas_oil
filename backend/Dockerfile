FROM python:3.13-slim AS build
ENV POETRY_VIRTUALENVS_IN_PROJECT=true
RUN pip install --no-cache-dir poetry==2.4.3
WORKDIR /app
COPY pyproject.toml poetry.lock* ./
RUN poetry install --only main --no-interaction --no-ansi

FROM python:3.13-slim
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN useradd --system --no-create-home atlasoil
WORKDIR /app
COPY --from=build /app/.venv ./.venv
COPY app ./app
USER atlasoil
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
