# mock-service

A small FastAPI service that mocks a real-world REST API. It exists to try
[rest-runner](../README.md) against something: rest-runner sends a list of
requests and writes a report with every response, and this service gives it
responses worth reading.

It exposes a single endpoint, `POST /orders` (also reachable as `POST /orders/`),
which validates the order it receives and answers:

| Case | Status | Body |
|---|---|---|
| The order is valid | `201` | `{"orderNumber": 10482, "status": "created"}` |
| A field fails validation | `400` | `{"orderNumber": 10482, "message": "error on phone"}` |
| The body is not a JSON object | `400` | `{"orderNumber": null, "message": "malformed body"}` |

The service validates only some fields **on purpose**. The point of the report
is to spot, by reading it, which validations are missing and which ones are too
strict.

The service keeps no state and has no authentication: it validates and answers.

## 1. Build the image and start the container

Docker must be running. From this folder:

```bash
docker build -t mock-service .
docker run --rm -p 8000:8000 mock-service
```

The service is now listening on `http://127.0.0.1:8000`. Stop it with `Ctrl+C`.

To publish it on another port, change the left side of `-p`. For example,
`-p 9000:8000` serves it on `http://127.0.0.1:9000`.

Rebuild the image after changing `mock-service.py` or `requirements.txt`.

### Without Docker

```bash
pip install -r requirements.txt
python mock-service.py
```

Run this way, the port is read from `config/config.yml`. The container does not
use that file: its port is the one given to `docker run -p`.

## 2. Test requests

The commands are written for bash (Git Bash on Windows). The bodies use only
ASCII characters because Git Bash on Windows does not send accented characters
typed on the command line as UTF-8, and the service would answer
`malformed body`.

A valid order, answered with `201`:

```bash
curl -i -X POST http://127.0.0.1:8000/orders \
  -H "Content-Type: application/json" \
  -d '{
    "orderNumber": 10482,
    "name": "Alejandro",
    "phone": "+34600123456",
    "email": "alejandro.fernandez@example.com",
    "member": true,
    "numberOfProducts": 2,
    "price": 45.5,
    "products": [
      {"name": "Coffee Beans", "box": "L", "price": 20.0},
      {"name": "Handmade Cookies", "box": "M", "price": 25.5}
    ]
  }'
```

```json
{"orderNumber":10482,"status":"created"}
```

The same order with a phone that has only 8 digits, answered with `400`:

```bash
curl -i -X POST http://127.0.0.1:8000/orders \
  -H "Content-Type: application/json" \
  -d '{
    "orderNumber": 10482,
    "name": "Alejandro",
    "phone": "+3460012345",
    "email": "alejandro.fernandez@example.com",
    "member": true,
    "numberOfProducts": 2,
    "price": 45.5,
    "products": [
      {"name": "Coffee Beans", "box": "L", "price": 20.0},
      {"name": "Handmade Cookies", "box": "M", "price": 25.5}
    ]
  }'
```

```json
{"orderNumber":10482,"message":"error on phone"}
```

`testcases.yml` is a rest-runner suite with 21 requests like these: valid
orders, one request per validation, and several orders the service accepts
without validating.

## 3. Swagger

With the service running, open:

- `http://127.0.0.1:8000/docs`: Swagger UI, where the endpoint can be tried from the browser.
- `http://127.0.0.1:8000/redoc`: the same documentation, read-only.
- `http://127.0.0.1:8000/openapi.json`: the OpenAPI specification.

Two things in Swagger differ from what the service does:

- Only `POST /orders` is listed. `POST /orders/` works the same but is hidden to avoid a duplicate entry.
- The documented error is a `422`, which FastAPI adds by default. The service always answers validation errors with `400`.

## Files

| File | Content |
|---|---|
| `mock-service.py` | The service. |
| `config/config.yml` | Port used when running without Docker. |
| `requirements.txt` | Python dependencies. |
| `Dockerfile`, `.dockerignore` | Container image. |
| `testcases.yml` | Example suite for rest-runner. |
