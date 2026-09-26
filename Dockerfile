FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 MPLBACKEND=Agg PORT=8000 SUNDIAL_CACHE=/tmp/sundial-web
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY app/requirements.txt app/requirements.txt
RUN pip install --no-cache-dir -r app/requirements.txt
COPY app app
COPY web web
WORKDIR /srv/app
EXPOSE 8000
# free hosts (Render, Cloud Run, Hugging Face Spaces) inject PORT
CMD ["sh", "-c", "uvicorn sundialweb.api:app --host 0.0.0.0 --port ${PORT}"]
