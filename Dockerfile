FROM python:3.14-slim-bookworm AS builder

WORKDIR /build
COPY requirements.txt requirements.docker.txt ./
RUN python -m venv /opt/soplax \
    && /opt/soplax/bin/pip install --no-cache-dir --disable-pip-version-check -r requirements.docker.txt

FROM python:3.14-slim-bookworm AS runtime

ENV PATH="/opt/soplax/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DJANGO_ENV=production \
    DJANGO_SETTINGS_MODULE=project.settings_docker

WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 soplax \
    && useradd --system --uid 10001 --gid soplax --no-create-home soplax \
    && install -d -o soplax -g soplax /app/staticfiles

COPY --from=builder /opt/soplax /opt/soplax
COPY manage.py ./
COPY project/ ./project/
COPY app/ ./app/
COPY static/ ./static/

USER soplax
RUN DJANGO_ENV=development \
    DJANGO_SECRET_KEY="$(python -c 'from secrets import token_urlsafe; print(token_urlsafe(48))')" \
    python manage.py collectstatic --noinput

EXPOSE 8000
CMD ["gunicorn", "project.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "4", "--timeout", "120"]
