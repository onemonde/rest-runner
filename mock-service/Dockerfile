FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mock-service.py .

EXPOSE 8000

# Inside the container the service must listen on 0.0.0.0 to be reachable from
# the host, so uvicorn is started directly and config/config.yml is not used: the port
# seen from outside is chosen with "docker run -p".
CMD ["uvicorn", "mock-service:app", "--host", "0.0.0.0", "--port", "8000"]
