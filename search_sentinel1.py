"""
Searches the Copernicus Data Space Ecosystem catalogue for Sentinel-1 GRD
scenes covering the Storebælt strait within a given date range. Does NOT
download anything yet — just lists what's available and saves the full
catalogue to disk so download_sentinel1.py can pick specific scenes.
"""
import json

import requests

# Storebælt bounding box, as a WKT polygon (same area as our AIS filter)
AOI_WKT = (
    "POLYGON((10.5 55.0, 11.3 55.0, 11.3 55.6, 10.5 55.6, 10.5 55.0))"
)

START_DATE = "2026-05-01"
END_DATE = "2026-06-30"

TOKEN_URL = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
CATALOGUE_URL = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"


def get_access_token(username: str, password: str) -> str:
    """Log in once to get a temporary access token (valid ~10 minutes)."""
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


def search_sentinel1(token: str) -> list[dict]:
    """Query the catalogue for Sentinel-1 GRD scenes over our area/date range."""
    filter_query = (
        "Collection/Name eq 'SENTINEL-1' "
        f"and OData.CSC.Intersects(area=geography'SRID=4326;{AOI_WKT}') "
        f"and ContentDate/Start gt {START_DATE}T00:00:00.000Z "
        f"and ContentDate/Start lt {END_DATE}T00:00:00.000Z "
        "and Attributes/OData.CSC.StringAttribute/any(att:att/Name eq 'productType' and att/Value eq 'GRD')"
    )

    response = requests.get(
        CATALOGUE_URL,
        params={"$filter": filter_query, "$orderby": "ContentDate/Start", "$top": 1000},
        headers={"Authorization": f"Bearer {token}"},
    )
    response.raise_for_status()
    return response.json()["value"]


if __name__ == "__main__":
    username = input("Copernicus e-posta: ")
    password = input("Copernicus şifre: ")

    print("Giriş yapılıyor...")
    token = get_access_token(username, password)

    print("Sentinel-1 sahneleri aranıyor...")
    results = search_sentinel1(token)

    print(f"\n{len(results)} sahne bulundu.\n")
    for product in results:
        print(f"- {product['Name']}  |  {product['ContentDate']['Start']}")

    with open("data/sentinel1_catalogue.json", "w") as f:
        json.dump(results, f)
    print("\nFull catalogue saved -> data/sentinel1_catalogue.json")