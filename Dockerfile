FROM python:3.12-slim

# git is needed to install daftlistings from GitHub (see requirements.txt).
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app app
COPY tests tests
COPY pytest.ini .
RUN python -m pytest -q

ENV DATA_DIR=/data PYTHONUNBUFFERED=1 PORT=8000
VOLUME /data
EXPOSE 8000
HEALTHCHECK CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/health')"
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
