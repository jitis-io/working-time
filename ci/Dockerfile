FROM node:24-bookworm-slim AS node

FROM python:3.14-slim-bookworm AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
	PIP_DISABLE_PIP_VERSION_CHECK=1 \
	PYTHONDONTWRITEBYTECODE=1 \
	PYTHONUNBUFFERED=1

RUN apt-get update \
	&& apt-get install --yes --no-install-recommends \
		build-essential \
		cron \
		curl \
		git \
		libffi-dev \
		libmariadb-dev \
		libssl-dev \
		mariadb-client \
		pkg-config \
		redis-server \
	&& rm -rf /var/lib/apt/lists/* \
	&& pip install babel frappe-bench ruff \
	&& useradd --create-home --shell /bin/bash runner

COPY --from=node /usr/local/ /usr/local/
COPY --from=node /opt/yarn-v1.22.22/ /opt/yarn-v1.22.22/

RUN node --version && yarn --version

USER runner
WORKDIR /workspace

FROM runtime AS base

COPY --chown=runner:runner . /workspace

FROM runtime AS integration-deps

USER root
RUN apt-get update \
	&& apt-get install --yes --no-install-recommends chromium \
	&& rm -rf /var/lib/apt/lists/*

USER runner

FROM integration-deps AS integration

COPY --chown=runner:runner . /workspace
