import os
import random
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import psycopg2
from docx import Document
from faker import Faker
from fpdf import FPDF, XPos, YPos

SEED = 42
PRODUCT_COUNT = 200
TENDER_COUNT = 3
TENDER_REQUIREMENT_RANGE = (15, 20)
DATA_DIR = Path("data")

CATEGORIES = ("Laptop", "Monitor", "Office Equipment")
CATEGORY_CODES = {
    "Laptop": "LAP",
    "Monitor": "MON",
    "Office Equipment": "OFF",
}
POLICIES = {
    "warranty_policy.docx": (
        "TechNest Warranty Policy: All hardware items include a standard "
        "2-year limited hardware warranty covering manufacturing defects. "
        "Extended support packages are available upon request."
    ),
    "returns_policy.docx": (
        "TechNest Returns & Refunds Policy: Unopened items may be returned "
        "within 30 days of purchase for a full refund. Defective merchandise "
        "can be exchanged or refunded within 14 days of delivery."
    ),
    "delivery_policy.docx": (
        "TechNest Delivery & Shipping Terms: Standard ground shipping takes "
        "3-5 business days. Express shipping is available for corporate orders. "
        "Free delivery applies to bulk orders over $1,000."
    ),
}


@dataclass(frozen=True)
class Product:
    product_code: str
    name: str
    category: str
    price: float
    stock_quantity: int
    iso_cert: str | None
    ce_certified: str


def wrap_to_width(pdf: FPDF, text: str, max_width: float) -> list[str]:
    words = text.split()
    lines = []
    current = ""

    for word in words:
        candidate = f"{current} {word}".strip()
        if pdf.get_string_width(candidate) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word

    if current:
        lines.append(current)

    return lines


def generate_products() -> list[Product]:
    rng = random.Random(SEED)
    products = []

    for index in range(1, PRODUCT_COUNT + 1):
        category = CATEGORIES[(index - 1) % len(CATEGORIES)]
        code = CATEGORY_CODES[category]

        if category == "Laptop":
            name = (
                f"TechNest Book {rng.choice(['Pro', 'Air', 'Ultra'])} "
                f"{rng.randint(13, 17)}"
            )
            price = round(rng.uniform(700.0, 2200.0), 2)
        elif category == "Monitor":
            name = (
                f"TechView {rng.randint(24, 34)}-inch "
                f"{rng.choice(['4K', 'Ultrawide', 'Ergo'])} Display"
            )
            price = round(rng.uniform(180.0, 650.0), 2)
        else:
            name = (
                "TechOffice "
                f"{rng.choice(['Ergonomic Chair', 'Standing Desk', 'Docking Station', 'Wireless Keyboard Combo'])}"
            )
            price = round(rng.uniform(50.0, 400.0), 2)

        iso_certified = rng.choice((True, True, True, False))
        stock_quantity = 0 if rng.random() < 0.1 else rng.randint(1, 150)
        products.append(
            Product(
                product_code=f"TN-{code}-{index:04d}",
                name=name,
                category=category,
                price=price,
                stock_quantity=stock_quantity,
                iso_cert=(
                    f"ISO-9001-{rng.randint(10000, 99999)}" if iso_certified else None
                ),
                ce_certified=rng.choice(("Yes", "Yes", "Yes", "No")),
            )
        )

    return products


def seed_database(products: list[Product]) -> None:
    conn = psycopg2.connect(
        dbname=os.getenv("PGDATABASE", "technest_db"),
        user=os.getenv("PGUSER", "technest_user"),
        password=os.getenv("PGPASSWORD", "technest_password"),
        host=os.getenv("PGHOST", "localhost"),
        port=os.getenv("PGPORT", "5432"),
    )

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS products (
                        id SERIAL PRIMARY KEY,
                        product_code VARCHAR(50) UNIQUE NOT NULL,
                        name VARCHAR(100) NOT NULL,
                        category VARCHAR(50) NOT NULL,
                        price NUMERIC(10, 2) NOT NULL,
                        stock_quantity INT NOT NULL
                    )
                    """)
                cur.executemany(
                    """
                    INSERT INTO products
                        (product_code, name, category, price, stock_quantity)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (product_code) DO UPDATE SET
                        name = EXCLUDED.name,
                        category = EXCLUDED.category,
                        price = EXCLUDED.price,
                        stock_quantity = EXCLUDED.stock_quantity
                    """,
                    [
                        (
                            product.product_code,
                            product.name,
                            product.category,
                            product.price,
                            product.stock_quantity,
                        )
                        for product in products
                    ],
                )
                cur.execute(
                    """
                    DELETE FROM products
                    WHERE LEFT(product_code, 7) IN ('TN-LAP-', 'TN-MON-', 'TN-OFF-')
                    AND NOT (product_code = ANY(%s))
                    """,
                    ([product.product_code for product in products],),
                )
        print(f"Seeded {len(products)} products in PostgreSQL.")
    finally:
        conn.close()


def write_product_pdfs(products: list[Product], directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    expected_names = {f"{product.product_code}.pdf" for product in products}
    generated_name = re.compile(r"TN-(?:LAP|MON|OFF)-\d{4}\.pdf")

    for path in directory.iterdir():
        if (
            path.is_file()
            and generated_name.fullmatch(path.name)
            and path.name not in expected_names
        ):
            path.unlink()

    faker = Faker()
    faker.seed_instance(SEED)
    for product in products:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)

        pdf.cell(
            200,
            10,
            text="TechNest Product Datasheet",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
            align="C",
        )
        pdf.cell(
            200,
            10,
            text=f"Product Code: {product.product_code}",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        pdf.cell(
            200, 10, text=f"Name: {product.name}", new_x=XPos.LMARGIN, new_y=YPos.NEXT
        )
        pdf.cell(
            200,
            10,
            text=f"Category: {product.category}",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        pdf.cell(
            200,
            10,
            text=f"Price: ${product.price:.2f}",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        pdf.cell(
            200,
            10,
            text=f"Stock quantity: {product.stock_quantity}",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        pdf.ln(5)
        pdf.multi_cell(
            190,
            10,
            text=(
                f"Specifications & Overview:\n{faker.paragraph(nb_sentences=5)}\n\n"
                "Designed for enterprise and modern office productivity. "
                "Fully tested and compliant with TechNest strict quality guidelines."
            ),
        )
        pdf.output(str(directory / f"{product.product_code}.pdf"))

    print(f"Generated {len(products)} product datasheets.")


def write_policies(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for filename, content in POLICIES.items():
        doc = Document()
        title = filename.removesuffix(".docx").replace("_", " ").title()
        doc.add_heading(title, level=1)
        doc.add_paragraph(content)
        doc.save(directory / filename)


def write_certificates(products: list[Product], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    certificates = pd.DataFrame(
        [
            {
                "product_code": product.product_code,
                "product_name": product.name,
                "iso_cert": product.iso_cert,
                "ce_certified": product.ce_certified,
            }
            for product in products
        ]
    )
    certificates.to_excel(path, index=False)
    print(f"Generated certificates for {len(products)} products.")


def write_tenders(products: list[Product], directory: Path) -> list[dict[str, object]]:
    directory.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    expected_names = {f"tender_{number}.pdf" for number in range(1, TENDER_COUNT + 1)}
    for path in directory.glob("tender_*.pdf"):
        if (
            re.fullmatch(r"tender_\d+\.pdf", path.name)
            and path.name not in expected_names
        ):
            path.unlink()

    status_groups = {
        "Yes": [
            product
            for product in products
            if product.iso_cert is not None and product.stock_quantity > 0
        ],
        "Partly": [
            product
            for product in products
            if (product.iso_cert is not None) != (product.stock_quantity > 0)
        ],
        "No": [
            product
            for product in products
            if product.iso_cert is None and product.stock_quantity == 0
        ],
    }
    if any(not group for group in status_groups.values()):
        raise ValueError(
            "Generated products must cover Yes, Partly, and No tender outcomes."
        )

    answer_key = []
    for tender_index in range(1, TENDER_COUNT + 1):
        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.set_margins(15, 15)
        pdf.add_page()
        pdf.set_font("Helvetica", size=11)

        page_width = pdf.w - 30
        pdf.cell(
            page_width,
            10,
            text=f"Corporate Procurement Tender #{tender_index}",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
            align="C",
        )
        pdf.cell(
            page_width,
            8,
            text=f"Buyer: Enterprise Procurement Corp Q{tender_index}",
            new_x=XPos.LMARGIN,
            new_y=YPos.NEXT,
        )
        pdf.multi_cell(
            page_width,
            8,
            text=(
                "The supplier (TechNest) must fulfill the following mandatory technical "
                "and compliance specifications to qualify for this contract:"
            ),
        )

        requirement_count = rng.randint(*TENDER_REQUIREMENT_RANGE)
        selected_products = [rng.choice(group) for group in status_groups.values()]
        remaining_products = [
            product for product in products if product not in selected_products
        ]
        selected_products.extend(rng.sample(remaining_products, requirement_count - 3))
        rng.shuffle(selected_products)
        for requirement_number, product in enumerate(selected_products, start=1):
            requirement = (
                f"Requirement {requirement_number}: {product.product_code} "
                "must be ISO-certified and stock-ready."
            )
            has_certificate = product.iso_cert is not None
            has_stock = product.stock_quantity > 0
            outcome = (
                "Yes"
                if has_certificate and has_stock
                else "No" if not has_certificate and not has_stock else "Partly"
            )
            certificate_evidence = (
                f"ISO certificate {product.iso_cert}"
                if has_certificate
                else "No ISO certificate listed"
            )
            answer_key.append(
                {
                    "tender_file": f"tender_{tender_index}.pdf",
                    "requirement_number": requirement_number,
                    "product_code": product.product_code,
                    "expected_result": outcome,
                    "evidence": (
                        f"{certificate_evidence}; stock quantity "
                        f"{product.stock_quantity}"
                    ),
                }
            )
            bullet_width = 10
            text_width = page_width - bullet_width
            left_indent = 15

            for line in wrap_to_width(pdf, f"- {requirement}", text_width):
                pdf.set_x(left_indent)
                if line.startswith("- "):
                    pdf.cell(bullet_width, 6, text="-", align="L")
                    pdf.set_x(left_indent + bullet_width)
                    pdf.multi_cell(text_width, 6, text=line[2:], align="L")
                else:
                    pdf.cell(bullet_width, 6, text="", align="L")
                    pdf.set_x(left_indent + bullet_width)
                    pdf.multi_cell(text_width, 6, text=line, align="L")

        pdf.output(str(directory / f"tender_{tender_index}.pdf"))

    print(
        f"Generated {TENDER_COUNT} tenders with {TENDER_REQUIREMENT_RANGE[0]}-"
        f"{TENDER_REQUIREMENT_RANGE[1]} requirements each."
    )
    return answer_key


def write_tender_answer_key(answer_key: list[dict[str, object]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(answer_key).to_excel(path, index=False)


def main() -> None:
    products = generate_products()
    seed_database(products)
    write_product_pdfs(products, DATA_DIR / "pdfs")
    write_policies(DATA_DIR / "policies")
    write_certificates(products, DATA_DIR / "certificates.xlsx")
    answer_key = write_tenders(products, DATA_DIR / "tenders")
    write_tender_answer_key(answer_key, DATA_DIR / "tender_answer_key.xlsx")
    print("Sample data generation complete.")


if __name__ == "__main__":
    main()
