"""OpenFoodFacts product lookup integration."""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


class ProductLookupError(Exception):
    """Raised when the OpenFoodFacts service cannot be reached or parsed."""


def lookup_product(*, barcode=None, name=None, timeout=5):
    """Look up a product by barcode or name and return normalized details."""
    if bool(barcode) == bool(name):
        raise ValueError("Provide exactly one of barcode or name")

    if barcode:
        url = f"https://world.openfoodfacts.org/api/v2/product/{quote(barcode, safe='')}.json"
    else:
        query = urlencode(
            {
                "search_terms": name,
                "search_simple": 1,
                "action": "process",
                "json": 1,
                "page_size": 1,
            }
        )
        url = f"https://world.openfoodfacts.org/cgi/search.pl?{query}"

    request = Request(url, headers={"User-Agent": "InventoryManagement/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProductLookupError(f"OpenFoodFacts lookup failed: {error}") from error

    if not isinstance(payload, dict):
        raise ProductLookupError("OpenFoodFacts returned an invalid response")

    if barcode:
        product = payload.get("product") if payload.get("status") == 1 else None
    else:
        products = payload.get("products")
        product = products[0] if isinstance(products, list) and products else None

    if not isinstance(product, dict):
        return None

    return {
        "name": product.get("product_name") or product.get("product_name_en"),
        "barcode": product.get("code") or barcode,
        "brands": product.get("brands"),
        "category": product.get("categories"),
        "description": product.get("ingredients_text"),
        "image_url": product.get("image_url"),
    }
