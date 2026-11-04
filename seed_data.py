import os
import random

import psycopg2
import pandas as pd
from docx import Document
from fpdf import FPDF, XPos, YPos
from faker import Faker

fake = Faker()


def wrap_to_width(pdf, text, max_width):
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


# creating local directories for files
os.makedirs("data", exist_ok=True)
os.makedirs("data/pdfs", exist_ok=True)
os.makedirs("data/policies", exist_ok=True)
os.makedirs("data/polices", exist_ok=True)
os.makedirs("data/tenders", exist_ok=True)

# 1. Connecting and populating PostgreSQL database
print("Connecting to PostgreSQL and seeding products...")
conn = psycopg2.connect(
    dbname="technest_db",
    user="technest_user",
    password="technest_password",
    host="localhost",
    port="5432",
)
cur = conn.cursor()

cur.execute(
    """
    DROP TABLE IF EXISTS products;
    CREATE TABLE products (
        id SERIAL PRIMARY KEY,
        product_code VARCHAR(50) UNIQUE NOT NULL,
        name VARCHAR(100) NOT NULL,
        category VARCHAR(50) NOT NULL,
        price NUMERIC(10, 2) NOT NULL,
        stock_quantity INT NOT NULL
    );
    """
)

categories = ["Laptop", "Monitor", "Office Equipment"]
categories_code_map = {"Laptop": "LAP", "Monitor": "MON", "Office Equipment": "OFF"}

products_data = []
cert_data = []

for i in range(1, 201):
    cat = random.choice(categories)
    code_prefix = categories_code_map[cat]
    product_code = f"TN-{code_prefix}-{i:04d}"

    # generating realistic names based on category
    if cat == "Laptop":
        name = f"TechNest Book {random.choice(['Pro', 'Air', 'Ultra'])} {random.randint(13, 17)}"
        price = round(random.uniform(700.0, 2200.0), 2)
    elif cat == "Monitor":
        name = f"TechView {random.randint(24, 34)}-inch {random.choice(['4K', 'Ultrawide', 'Ergo'])} Display"
        price = round(random.uniform(180.0, 650.0), 2)
    else:
        name = f"TechOffice {random.choice(['Ergonomic Chair', 'Standing Desk', 'Docking Station', 'Wireless Keyboard Combo'])}"
        price = round(random.uniform(50.0, 400.0), 2)

    stock = random.randint(0, 150)
    products_data.append((product_code, name, cat, price, stock))

    # collecting data for excel certificates
    cert_data.append(
        {
            "product_code": product_code,
            "product_name": name,
            "iso_cert": f"ISO-9001-{random.randint(10000, 99999)}",
            "ce_certified": random.choice(["Yes", "Yes", "Yes", "No"]),
        }
    )

cur.executemany(
    """
    INSERT INTO products (product_code, name, category, price, stock_quantity)
    VALUES (%s, %s, %s, %s, %s)
    """,
    products_data,
)
conn.commit()
print(f"Successfully inserted {len(products_data)} products into PostgreSQL.")

# 2. Generating product datasheets (PDF Files)
print("Generating product PDF datasheets...")
for code, name, cat, price, stock in products_data:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=12)

    pdf.cell(200, 10, text="TechNest Product Datasheet", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.cell(200, 10, text=f"Product Code: {code}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="L")
    pdf.cell(200, 10, text=f"Name: {name}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="L")
    pdf.cell(200, 10, text=f"Category: {cat}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="L")
    pdf.cell(200, 10, text=f"Price: ${price}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="L")

    pdf.ln(10)
    pdf.multi_cell(
        190,
        10,
        text=(
            f"Specifications & Overview:\n{fake.paragraph(nb_sentences=5)}\n\n"
            "Designed for enterprise and modern office productivity. "
            "Fully tested and compliant with TechNest strict quality guidelines."
        ),
    )
    pdf.output(f"data/pdfs/{code}.pdf")

print(f"Saved {len(products_data)} product datasheets.")

# 3. Generating company policies (Word Files)
print("Generating company policy Word documents...")
policies = {
    "warranty_policy.docx": "TechNest Warranty Policy: All hardware items include a standard 2-year limited hardware warranty covering manufacturing defects. Extended support packages are available upon request.",
    "returns_policy.docx": "TechNest Returns & Refunds Policy: Unopened items may be returned within 30 days of purchase for a full refund. Defective merchandise can be exchanged or refunded within 14 days of delivery.",
    "delivery_policy.docx": "TechNest Delivery & Shipping Terms: Standard ground shipping takes 3-5 business days. Express shipping is available for corporate orders. Free delivery applies to bulk orders over $1,000.",
}

for filename, content in policies.items():
    doc = Document()
    doc.add_heading(filename.replace("_", " ").title().replace(".docx", ""), level=1)
    doc.add_paragraph(content)
    doc.save(f"data/policies/{filename}")

# 4. Generate Certificates (Excel file)
print("Generating Excel compliance certificates...")
df_certs = pd.DataFrame(cert_data)
df_certs.to_excel("data/certificates.xlsx", index=False)

# 5. Generate sample buyer tenders
print("Generating sample buyer tenders...")
for tender_idx in range(1, 4):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(15, 15)
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)

    page_width = pdf.w - 30
    pdf.cell(page_width, 10, text=f"Corporate Procurement Tender #{tender_idx}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="C")
    pdf.cell(page_width, 8, text=f"Buyer: Enterprise Procurement Corp Q{tender_idx}", new_x=XPos.LMARGIN, new_y=YPos.NEXT, align="L")

    pdf.multi_cell(
        page_width,
        8,
        text=(
            "The supplier (TechNest) must fulfill the following mandatory technical and compliance specifications "
            "to qualify for this contract:"
        ),
    )

    num_reqs = random.randint(8, 12)
    for req_num in range(1, num_reqs + 1):
        sample_code = random.choice(products_data)[0]
        req_text = f"Requirement {req_num}: {sample_code} must be ISO-certified and stock-ready."

        bullet_width = 10
        text_block_width = page_width - bullet_width
        left_indent = 15

        for wrapped_line in wrap_to_width(pdf, f"- {req_text}", text_block_width):
            pdf.set_x(left_indent)
            if wrapped_line.startswith("- "):
                pdf.cell(bullet_width, 6, text="-", align="L")
                pdf.set_x(left_indent + bullet_width)
                pdf.multi_cell(text_block_width, 6, text=wrapped_line[2:], align="L")
            else:
                pdf.cell(bullet_width, 6, text="", align="L")
                pdf.set_x(left_indent + bullet_width)
                pdf.multi_cell(text_block_width, 6, text=wrapped_line, align="L")

    pdf.output(f"data/tenders/tender_{tender_idx}.pdf")

cur.close()
conn.close()
print("All fake data successfully generated and structured for Week 1!")