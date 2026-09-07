FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 VGSELECT_HOST=0.0.0.0 VGSELECT_PORT=8080
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir '.[service]'
# Optional: add the Claude-powered `describe` endpoint
# RUN pip install --no-cache-dir '.[service,llm]'
RUN useradd -m vgselect && mkdir -p /scan && chown vgselect /scan
USER vgselect
EXPOSE 8080
HEALTHCHECK CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health').status==200 else 1)"
CMD ["vgselect-service"]
