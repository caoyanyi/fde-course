FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/data \
    COURSE_PATH=/app/course/curriculum.json

WORKDIR /app/backend
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 fde \
    && useradd --uid 10001 --gid 10001 --no-create-home fde \
    && mkdir -p /app/data \
    && chown 10001:10001 /app/data \
    && chmod 700 /app/data
COPY --chown=10001:10001 backend/app ./app
COPY --chown=10001:10001 course /app/course
USER 10001:10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
