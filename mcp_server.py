"""Narrow MCP tools for read-only product and document retrieval."""

import asyncio
from collections.abc import Callable
from typing import Any

import psycopg2
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from qdrant_client.http.exceptions import (
    ResponseHandlingException,
    UnexpectedResponse,
)

from policy_rag import PolicyRAG, _build_rag
from product_queries import (
    MAX_SEARCH_LIMIT,
    ProductRecord,
    get_product_by_code,
    search_products,
)


def _product_dict(product: ProductRecord) -> dict[str, Any]:
    return {
        "product_code": product.product_code,
        "name": product.name,
        "category": product.category,
        "price": str(product.price),
        "stock_quantity": product.stock_quantity,
    }


def build_mcp_server(rag_factory: Callable[[], PolicyRAG] = _build_rag) -> MCPServer:
    """Create the TechNest MCP server without exposing write operations."""

    server = MCPServer(
        "technest-assist",
        description="Read-only TechNest product and document retrieval",
    )

    @server.tool(
        name="get_product_by_code",
        description="Return one seeded product by exact catalog code, or null if absent.",
    )
    def get_product(product_code: str) -> dict[str, Any] | None:
        try:
            product = get_product_by_code(product_code)
        except ValueError as error:
            raise ToolError(f"Invalid product lookup: {error}") from error
        except psycopg2.Error as error:
            raise ToolError("Product database unavailable.") from error
        return _product_dict(product) if product is not None else None

    @server.tool(
        name="search_products",
        description="Search seeded products by name substring and/or exact category.",
    )
    def find_products(
        name: str | None = None,
        category: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= MAX_SEARCH_LIMIT
        ):
            raise ToolError(f"Limit must be an integer from 1 to {MAX_SEARCH_LIMIT}.")
        try:
            products = search_products(name=name, category=category, limit=limit)
        except ValueError as error:
            raise ToolError(f"Invalid product search: {error}") from error
        except psycopg2.Error as error:
            raise ToolError("Product database unavailable.") from error
        return [_product_dict(product) for product in products]

    @server.tool(
        name="search_documents",
        description="Retrieve policy or PDF document passages with source metadata.",
    )
    def find_documents(question: str, limit: int = 3) -> list[dict[str, Any]]:
        if not isinstance(question, str) or not question.strip():
            raise ToolError("Question must not be empty.")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 10
        ):
            raise ToolError("Limit must be an integer from 1 to 10.")
        try:
            rag = rag_factory()
            results = rag.search(question, limit=limit)
        except (
            RuntimeError,
            ValueError,
            OSError,
            ResponseHandlingException,
            UnexpectedResponse,
        ) as error:
            raise ToolError(f"Document retrieval failed: {error}") from error
        return [
            {
                "source": result.source,
                "section_id": result.section_id,
                "text": result.text,
                "score": result.score,
            }
            for result in results
        ]

    return server


server = build_mcp_server()


if __name__ == "__main__":
    asyncio.run(server.run_stdio_async())
