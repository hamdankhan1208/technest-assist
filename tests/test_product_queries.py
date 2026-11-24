from decimal import Decimal

import psycopg2
import pytest

import product_queries
from product_queries import ProductRecord, get_product_by_code, search_products

PRODUCT_ROW = (
    "TN-LAP-0001",
    "TechNest Book Ultra 13",
    "Laptop",
    Decimal("737.52"),
    36,
)


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.query = None
        self.parameters = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, query, parameters):
        self.query = query
        self.parameters = parameters

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, rows):
        self.cursor_instance = FakeCursor(rows)
        self.readonly = None
        self.closed = False

    def set_session(self, *, readonly):
        self.readonly = readonly

    def cursor(self):
        return self.cursor_instance

    def close(self):
        self.closed = True


@pytest.fixture
def database(monkeypatch):
    state = {}

    def connect(**kwargs):
        state["connection_kwargs"] = kwargs
        state["connection"] = FakeConnection(state.get("rows", []))
        return state["connection"]

    monkeypatch.setattr(product_queries.psycopg2, "connect", connect)
    return state


def test_get_product_by_code_returns_typed_product_and_uses_read_only_parameterized_query(
    database,
):
    database["rows"] = [PRODUCT_ROW]

    result = get_product_by_code(" tn-lap-0001 ")

    assert result == ProductRecord(*PRODUCT_ROW)
    assert database["connection"].readonly is True
    assert database["connection"].cursor_instance.parameters == ("TN-LAP-0001",)
    assert "WHERE product_code = %s" in database["connection"].cursor_instance.query
    assert database["connection"].closed is True


def test_get_product_by_code_returns_none_when_product_does_not_exist(database):
    assert get_product_by_code("TN-LAP-9999") is None


def test_search_products_filters_by_name_and_category_and_escapes_like_wildcards(
    database,
):
    database["rows"] = [PRODUCT_ROW]

    results = search_products(name="Ultra_100%", category=" laptop ", limit=3)

    assert results == (ProductRecord(*PRODUCT_ROW),)
    cursor = database["connection"].cursor_instance
    assert "name ILIKE %s ESCAPE '!'" in cursor.query
    assert "LOWER(category) = LOWER(%s)" in cursor.query
    assert cursor.parameters == ("%Ultra!_100!%%", "laptop", 3)
    assert database["connection"].readonly is True


@pytest.mark.parametrize(
    "product_code",
    ["", "not-a-code", "TN-LAP-0001' OR 1=1 --", None],
)
def test_get_product_by_code_rejects_invalid_input_without_connecting(
    database, product_code
):
    with pytest.raises(ValueError):
        get_product_by_code(product_code)

    assert "connection" not in database


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"name": " "},
        {"category": "Laptop", "limit": 0},
        {"name": "Laptop", "limit": 51},
        {"name": "Laptop", "limit": True},
    ],
)
def test_search_products_rejects_invalid_input_without_connecting(database, kwargs):
    with pytest.raises(ValueError):
        search_products(**kwargs)

    assert "connection" not in database


def test_search_products_propagates_database_errors_and_closes_connection(
    database, monkeypatch
):
    connection = FakeConnection([])

    class FailingCursor(FakeCursor):
        def execute(self, query, parameters):
            raise psycopg2.OperationalError("database unavailable")

    connection.cursor_instance = FailingCursor([])
    monkeypatch.setattr(
        product_queries.psycopg2, "connect", lambda **kwargs: connection
    )

    with pytest.raises(psycopg2.OperationalError, match="database unavailable"):
        search_products(category="Laptop")

    assert connection.closed is True
