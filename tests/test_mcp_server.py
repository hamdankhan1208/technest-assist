import asyncio
from decimal import Decimal

from mcp import Client

import mcp_server
from policy_rag import RetrievedChunk
from product_queries import ProductRecord


def call_tool(server, name, arguments=None):
    async def run():
        async with Client(server, mode="legacy") as client:
            return await client.call_tool(name, arguments or {})

    return asyncio.run(run())


def test_mcp_registration_exposes_only_read_and_document_tools():
    server = mcp_server.build_mcp_server(lambda: object())

    async def list_names():
        async with Client(server, mode="legacy") as client:
            tools = await client.list_tools()
            return {tool.name for tool in tools.tools}

    assert asyncio.run(list_names()) == {
        "get_product_by_code",
        "search_products",
        "search_documents",
    }


def test_get_product_by_code_known_and_missing(monkeypatch):
    known = ProductRecord("TN-LAP-0001", "Laptop One", "Laptop", Decimal("999.99"), 7)

    monkeypatch.setattr(
        mcp_server,
        "get_product_by_code",
        lambda code: known if code == known.product_code else None,
    )
    server = mcp_server.build_mcp_server(lambda: object())

    known_result = call_tool(
        server, "get_product_by_code", {"product_code": "TN-LAP-0001"}
    )
    missing_result = call_tool(
        server, "get_product_by_code", {"product_code": "TN-LAP-9999"}
    )

    assert known_result.structured_content["result"]["product_code"] == "TN-LAP-0001"
    assert known_result.structured_content["result"]["price"] == "999.99"
    assert missing_result.structured_content["result"] is None


def test_search_products_delegates_name_category_and_limit(monkeypatch):
    captured = {}

    def fake_search(name=None, category=None, limit=10):
        captured.update(name=name, category=category, limit=limit)
        return (
            ProductRecord(
                "TN-MON-0002", "Ultra Monitor", "Monitor", Decimal("450.00"), 3
            ),
        )

    monkeypatch.setattr(mcp_server, "search_products", fake_search)
    server = mcp_server.build_mcp_server(lambda: object())

    result = call_tool(
        server, "search_products", {"name": "Ultra", "category": "Monitor", "limit": 5}
    )

    assert captured == {"name": "Ultra", "category": "Monitor", "limit": 5}
    assert result.structured_content["result"][0]["stock_quantity"] == 3


def test_search_documents_returns_source_metadata(monkeypatch):
    class FakeRAG:
        def search(self, question, limit=3):
            assert question == "How long is the hardware warranty?"
            assert limit == 2
            return (
                RetrievedChunk(
                    source="warranty_policy.docx",
                    section_id="section-1",
                    text="Hardware includes a warranty.",
                    score=0.82,
                ),
            )

    server = mcp_server.build_mcp_server(lambda: FakeRAG())
    result = call_tool(
        server,
        "search_documents",
        {"question": "How long is the hardware warranty?", "limit": 2},
    )

    document = result.structured_content["result"][0]
    assert document["source"] == "warranty_policy.docx"
    assert document["section_id"] == "section-1"
    assert document["text"] == "Hardware includes a warranty."
    assert document["score"] == 0.82


def test_mcp_rejects_malformed_product_and_document_input(monkeypatch):
    monkeypatch.setattr(
        mcp_server,
        "get_product_by_code",
        lambda code: (_ for _ in ()).throw(ValueError("bad code")),
    )
    server = mcp_server.build_mcp_server(lambda: object())

    result = call_tool(server, "get_product_by_code", {"product_code": "bad"})
    assert result.is_error is True

    malformed_search = call_tool(server, "search_products", {"limit": 51})
    assert malformed_search.is_error is True

    malformed_document = call_tool(server, "search_documents", {"question": ""})
    assert malformed_document.is_error is True
