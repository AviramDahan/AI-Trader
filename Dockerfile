FROM python:3.11-slim-trixie
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MPLBACKEND=Agg MPLCONFIGDIR=/tmp/matplotlib
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates tzdata fonts-dejavu-core fonts-noto-core postgresql-client age rclone git openssh-client \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 10001 trader && useradd -m -u 10001 -g trader trader
WORKDIR /app
COPY service/requirements.txt service/requirements-telegram-reader.txt /app/service/
RUN pip install --no-cache-dir -r service/requirements.txt -r service/requirements-telegram-reader.txt
COPY --chown=10001:10001 service/server /app/service/server
COPY --chown=10001:10001 deploy /app/deploy
RUN mkdir -p /backup /reader /app/.runtime /app/service/server/logs /app/service/server/data \
    && chown -R 10001:10001 /backup /reader /app/.runtime /app/service/server/logs /app/service/server/data
USER 10001:10001
ENV PYTHONPATH=/app/service/server
ENTRYPOINT ["python", "/app/service/server/cloud_runtime.py"]
CMD ["api"]
