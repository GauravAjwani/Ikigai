# syntax=docker/dockerfile:1
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm install
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY precedent ./precedent
COPY agents ./agents
COPY tests ./tests
COPY infra ./infra
COPY --from=web /web/dist ./web/dist
EXPOSE 8080
CMD ["python", "-m", "uvicorn", "precedent.api:app", "--host", "0.0.0.0", "--port", "8080"]
