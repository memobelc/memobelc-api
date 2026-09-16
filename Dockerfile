FROM python:3.11-slim

WORKDIR /app

# Instalar dependências do sistema se necessário
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

RUN pip install "poetry==2.4.1"

COPY pyproject.toml poetry.lock ./
RUN poetry config virtualenvs.create false \
 && poetry install --no-interaction --no-ansi --only main --no-root

COPY . .

EXPOSE 5000

# Usuário não-root (segurança)
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

# Se tiver gunicorn.conf.py:
CMD ["gunicorn", "-c", "gunicorn.conf.py", "run:app"]

# OU sem arquivo de config:
# CMD ["gunicorn", "-w", "4", "-k", "gthread", "--threads", "2", "--timeout", "120", "--graceful-timeout", "30", "-b", "0.0.0.0:5000", "run:app"]