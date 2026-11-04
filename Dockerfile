# Web app: FastAPI backend serving the built React UI.
FROM node:22-alpine AS ui
WORKDIR /ui
COPY client/package.json client/package-lock.json ./
RUN npm ci
COPY client/ ./
RUN npm run build

FROM python:3.13-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY fieldserve_board ./fieldserve_board
COPY sync.py sheet.py submission.json ./
COPY --from=ui /ui/dist ./client/dist

RUN useradd --system --uid 10001 app && mkdir -p /app/data && chown -R app /app/data
USER app
VOLUME ["/app/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2).status == 200 else 1)"
CMD ["uvicorn", "fieldserve_board.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
