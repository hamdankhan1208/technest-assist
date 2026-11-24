"""Read-only product lookups against the seeded PostgreSQL catalog."""

import os
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import psycopg2

PRODUCT_CODE_PATTERN = re.compile(r"TN-(?:LAP|MON|OFF)-\d{4}", re.IGNORECASE)
DEFAULT_SEARCH_LIMIT = 10
MAX_SEARCH_LIMIT = 50


@dataclass(frozen=True)
class ProductRecord:
    """Stable product fields returned to support workflows."""

    product_code: str
    name: str
    category: str
    price: Decimal
    stock_quantity: int


def _validate_product_code(product_code: str) -> str:
    if not isinstance(product_code, str):
        raise ValueError("Product code must be a string.")

    normalized = product_code.strip().upper()
    if not PRODUCT_CODE_PATTERN.fullmatch(normalized):
        raise ValueError(
            "Product code must match TN-LAP-0001, TN-MON-0001, or TN-OFF-0001."
        )
    return normalized


def _validate_filter(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string when provided.")
    return value.strip()


def _read_products(
    query: str, parameters: tuple[Any, ...]
) -> tuple[ProductRecord, ...]:
    connection = psycopg2.connect(
        dbname=os.getenv("PGDATABASE", "technest_db"),
        user=os.getenv("PGUSER", "technest_user"),
        password=os.getenv("PGPASSWORD", "technest_password"),
        host=os.getenv("PGHOST", "localhost"),
        port=int(os.getenv("PGPORT", "5432")),
    )
    try:
        connection.set_session(readonly=True)
        with connection.cursor() as cursor:
            cursor.execute(query, parameters)
            rows = cursor.fetchall()
        return tuple(ProductRecord(*row) for row in rows)
    finally:
        connection.close()


def get_product_by_code(product_code: str) -> ProductRecord | None:
    """Return one product for its exact catalog code, or ``None`` if absent."""
    code = _validate_product_code(product_code)
    products = _read_products(
        """
        SELECT product_code, name, category, price, stock_quantity
        FROM products
        WHERE product_code = %s
        """,
        (code,),
    )
    return products[0] if products else None


def search_products(
    name: str | None = None,
    category: str | None = None,
    limit: int = DEFAULT_SEARCH_LIMIT,
) -> tuple[ProductRecord, ...]:
    """Search by a name substring and/or exact category, with a bounded result set."""
    normalized_name = _validate_filter(name, "Name")
    normalized_category = _validate_filter(category, "Category")
    if normalized_name is None and normalized_category is None:
        raise ValueError("Provide a name and/or category to search products.")
    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= MAX_SEARCH_LIMIT
    ):
        raise ValueError(f"Limit must be an integer from 1 to {MAX_SEARCH_LIMIT}.")

    conditions = []
    parameters: list[Any] = []
    if normalized_name is not None:
        escaped_name = (
            normalized_name.replace("!", "!!").replace("%", "!%").replace("_", "!_")
        )
        conditions.append("name ILIKE %s ESCAPE '!'")
        parameters.append(f"%{escaped_name}%")
    if normalized_category is not None:
        conditions.append("LOWER(category) = LOWER(%s)")
        parameters.append(normalized_category)
    parameters.append(limit)

    query = f"""
        SELECT product_code, name, category, price, stock_quantity
        FROM products
        WHERE {' AND '.join(conditions)}
        ORDER BY product_code
        LIMIT %s
    """
    return _read_products(query, tuple(parameters))
