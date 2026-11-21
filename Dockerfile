# Container image for running the website on a server (e.g. Scaleway).
# Build:  docker build -t bsc-tournaments .
# Run:    docker run -p 8080:8080 -v bsc-data:/data -e SECRET_KEY=... -e ADMIN_PASSWORD=... bsc-tournaments

FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# The database is stored in /data so it can live on a volume that survives restarts
ENV DATABASE_PATH=/data/badminton.db
ENV TIMEZONE=Europe/Amsterdam
ENV PORT=8080
EXPOSE 8080

# waitress is a simple, production-ready web server written in pure Python
CMD ["sh", "-c", "waitress-serve --host=0.0.0.0 --port=${PORT} app:app"]
