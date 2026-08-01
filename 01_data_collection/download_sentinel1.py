"""
Downloads a hand-picked subset of Sentinel-1 GRD scenes (spread across the
AIS collection window) from the Copernicus Data Space Ecosystem, using the
catalogue saved by search_sentinel1.py.
"""
import json
import os

import requests

TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
DOWNLOAD_URL_TEMPLATE = "https://zipper.dataspace.copernicus.eu/odata/v1/Products({product_id})/$value"

CATALOGUE_PATH = "data/sentinel1_catalogue.json"
OUTPUT_DIR = "data/sentinel1"

# One representative date roughly every 4-5 days, all within our AIS
# coverage window (2026-05-01 to 2026-06-10).
SELECTED_DATES = [
    "20260501", "20260504", "20260508", "20260515", "20260518",
    "20260522", "20260529", "20260601", "20260604", "20260609",
]


def get_access_token(username: str, password: str) -> str:
    response = requests.post(
        TOKEN_URL,
        data={
            "client_id": "cdse-public",
            "username": username,
            "password": password,
            "grant_type": "password",
        },
    )
    response.raise_for_status()
    return response.json()["access_token"]


def pick_products(catalogue: list[dict]) -> list[dict]:
    """Keep only the first product found for each date in SELECTED_DATES."""
    picked = []
    for date_str in SELECTED_DATES:
        match = next((p for p in catalogue if date_str in p["Name"]), None)
        if match:
            picked.append(match)
        else:
            print(f"Warning: no scene found for {date_str}")
    return picked


def download_product(product: dict, username: str, password: str, output_dir: str) -> None:
    """Get a fresh token right before each download (tokens expire after ~10 min)."""
    output_path = os.path.join(output_dir, f"{product['Name']}.zip")
    if os.path.exists(output_path):
        print(f"{product['Name']}: already downloaded, skipping.")
        return

    token = get_access_token(username, password)
    url = DOWNLOAD_URL_TEMPLATE.format(product_id=product["Id"])

    print(f"{product['Name']}: downloading...")
    response = requests.get(
        url,
        headers={"Authorization": f"Bearer {token}"},
        stream=True,
        allow_redirects=True,
    )
    response.raise_for_status()

    with open(output_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            f.write(chunk)

    print(f"{product['Name']}: done -> {output_path}")


if __name__ == "__main__":
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(CATALOGUE_PATH) as f:
        catalogue = json.load(f)

    products = pick_products(catalogue)
    print(f"\n{len(products)} scenes selected for download.\n")

    username = input("Copernicus e-posta: ")
    password = input("Copernicus şifre: ")

    for product in products:
        download_product(product, username, password, OUTPUT_DIR)

    print("\nAll downloads complete.")