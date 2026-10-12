"""mock-service: a mock REST service used to try rest-runner against.

Run it with:  python mock-service.py
"""

from pathlib import Path

import uvicorn
import yaml
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, EmailStr, Field

HOST = "127.0.0.1"
# Relative to the script's folder, not to the current directory.
CONFIG_FILE = Path(__file__).parent / "config" / "config.yml"

app = FastAPI(title="mock-service")


class Product(BaseModel):
    # Fields are required and typed, with no further rules.
    model_config = ConfigDict(strict=True)

    name: str
    box: str
    price: float


class Order(BaseModel):
    # Strict: a value of the wrong type is an error, it is never converted.
    model_config = ConfigDict(strict=True)

    orderNumber: int
    # Letters only (accents and ñ included): no digits, no spaces.
    name: str = Field(max_length=20, pattern=r"^\p{L}+$")
    phone: str = Field(pattern=r"^\+34\d{9}$")
    email: EmailStr
    member: bool
    numberOfProducts: int
    price: float
    products: list[Product]


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    """Turn FastAPI's 422 into a 400 that reports only the first failing field."""
    body = exc.body
    # ("body", "phone"), ("body", "products", 0, "price") or ("body", 12) for bad JSON
    location = exc.errors()[0]["loc"]
    if not isinstance(body, dict) or len(location) < 2 or not isinstance(location[1], str):
        content = {"orderNumber": None, "message": "malformed body"}
    else:
        order_number = body.get("orderNumber")
        if type(order_number) is not int:
            order_number = None
        content = {"orderNumber": order_number, "message": f"error on {location[1]}"}
    return JSONResponse(status_code=400, content=content)


@app.exception_handler(400)
async def unreadable_body(request: Request, exc: Exception):
    """FastAPI answers its own 400 when the body cannot even be decoded (not UTF-8)."""
    return JSONResponse(
        status_code=400, content={"orderNumber": None, "message": "malformed body"}
    )


@app.post("/orders", status_code=201)
@app.post("/orders/", status_code=201, include_in_schema=False)
async def create_order(order: Order):
    return {"orderNumber": order.orderNumber, "status": "created"}


def load_port():
    with open(CONFIG_FILE, encoding="utf-8") as config_file:
        return yaml.safe_load(config_file)["mock-service"]["port"]


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=load_port())
