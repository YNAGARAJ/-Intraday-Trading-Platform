# syntax=docker/dockerfile:1
#
# App 2 (Australia / ASX). Requires trading-system-base:dev to be built first:
#   docker build -f infra/docker/Dockerfile.base -t trading-system-base:dev .
FROM trading-system-base:dev

USER root
COPY shared/ /app/shared/
COPY apps/australia/ /app/apps/australia/
RUN chown -R trading:trading /app
USER trading

WORKDIR /app
ENV PYTHONPATH=/app

CMD ["python", "-m", "apps.australia.main"]
