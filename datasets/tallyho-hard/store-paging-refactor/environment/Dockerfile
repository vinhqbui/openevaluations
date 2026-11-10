FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates procps \
    && rm -rf /var/lib/apt/lists/* && pip install --no-cache-dir pytest==8.4.1 \
    && useradd -m -s /bin/bash agent
COPY src/ /app/
RUN cd /app && git -c init.defaultBranch=main init -q \
    && git -c user.name=oe -c user.email=oe@localhost add -A \
    && git -c user.name=oe -c user.email=oe@localhost -c commit.gpgsign=false commit -qm "tallyho 0.4.0" \
    && chown -R agent:agent /app
WORKDIR /app
