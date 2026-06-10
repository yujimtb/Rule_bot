FROM node:22-bookworm-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    VIRTUAL_ENV=/opt/venv \
    PATH=/home/appuser/.codex/bin:/opt/venv/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
    HOME=/home/appuser \
    CODEX_HOME=/home/appuser/.codex

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates bubblewrap ripgrep \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/venv \
    && npm install -g @openai/codex \
    && useradd --create-home --uid 10001 appuser \
    && mkdir -p /home/appuser/.codex/bin /home/appuser/usage \
    && chown -R appuser:appuser /home/appuser

COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY docker-entrypoint.sh /usr/local/bin/rulebot-entrypoint
RUN chmod +x /usr/local/bin/rulebot-entrypoint

USER appuser

ENTRYPOINT ["rulebot-entrypoint"]
CMD ["python", "-m", "rulebot.answer_service"]
