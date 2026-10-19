FROM python:3.11-slim-trixie
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MPLBACKEND=Agg MPLCONFIGDIR=/tmp/matplotlib
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates tzdata fonts-dejavu-core fonts-noto-core postgresql-client age rclone git openssh-client \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -g 10001 trader && useradd -m -u 10001 -g trader trader
WORKDIR /app
COPY service/requirements.txt service/requirements-telegram-reader.txt /app/service/
RUN pip install --no-cache-dir -r service/requirements.txt -r service/requirements-telegram-reader.txt
COPY --chown=10001:10001 service/server /app/service/server
ARG ENTRY_DISCOVERY_ROLE=candidate
RUN ENTRY_DISCOVERY_ROLE="$ENTRY_DISCOVERY_ROLE" python -c "import os,pathlib; role=os.environ['ENTRY_DISCOVERY_ROLE']; assert role in ('candidate','bridge'); p=pathlib.Path('/app/service/server/entry_discovery_capabilities.py'); source=p.read_text(); assert source.count(\"BUILD_ROLE = 'candidate'\")==1; p.write_text(source.replace(\"BUILD_ROLE = 'candidate'\", 'BUILD_ROLE = '+repr(role))); p.chmod(0o444)" \
    && chown root:root /app/service/server /app/service/server/entry_discovery_capabilities.py \
    && chmod 755 /app/service/server
COPY --chown=10001:10001 deploy /app/deploy
RUN mkdir -p /backup /reader /app/.runtime /app/service/server/logs /app/service/server/data \
    && chown -R 10001:10001 /backup /reader /app/.runtime /app/service/server/logs /app/service/server/data
USER 10001:10001
ARG BUILD_SHA=unknown
ENV BUILD_SHA=$BUILD_SHA
ENV PYTHONPATH=/app/service/server
ENTRYPOINT ["python", "/app/service/server/cloud_runtime.py"]
CMD ["api"]
