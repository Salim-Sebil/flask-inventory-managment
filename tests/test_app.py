import io
import json
from unittest.mock import patch

import pytest

import app as inventory_app
import product_lookup


@pytest.fixture()
def client(tmp_path):
    application = inventory_app.create_app(
        {"TESTING": True, "DATABASE": str(tmp_path / "inventory.sqlite3")}
    )
    return application.test_client()


def test_inventory_crud_lifecycle(client):
    created_response = client.post(
        "/api/items",
        json={
            "name": "Coffee",
            "barcode": "012345",
            "category": "Beverages",
            "quantity": 8,
            "price": 4.5,
            "description": "Ground coffee",
        },
    )
    assert created_response.status_code == 201
    item = created_response.get_json()
    assert item["name"] == "Coffee"
    assert item["barcode"] == "012345"
    item_id = item["id"]

    assert client.get("/api/items").get_json() == [item]
    assert client.get(f"/api/items/{item_id}").get_json() == item

    updated = client.patch(
        f"/api/items/{item_id}", json={"quantity": 5, "price": 3.75}
    )
    assert updated.status_code == 200
    assert updated.get_json()["quantity"] == 5
    assert updated.get_json()["price"] == 3.75
    assert updated.get_json()["name"] == "Coffee"

    assert client.delete(f"/api/items/{item_id}").status_code == 204
    assert client.get(f"/api/items/{item_id}").status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"name": "Tea", "quantity": -1, "price": 2.0},
        {"name": "Tea", "quantity": True, "price": 2.0},
        {"name": "Tea", "quantity": 2**63, "price": 2.0},
        {"name": "Tea", "quantity": 1, "price": float("nan")},
        {"name": "Tea", "quantity": 1, "price": 10**1000},
        {"name": "Tea", "quantity": 1, "price": 2.0, "unexpected": "x"},
    ],
)
def test_create_rejects_invalid_items(client, payload):
    response = client.post("/api/items", json=payload)
    assert response.status_code == 400
    assert "error" in response.get_json()


def test_create_requires_json_object(client):
    response = client.post("/api/items", data="not-json")
    assert response.status_code == 400
    assert response.get_json()["error"] == "Request body must be a JSON object"


def test_duplicate_barcode_is_conflict(client):
    item = {"name": "Tea", "barcode": "123", "quantity": 1, "price": 2.0}
    assert client.post("/api/items", json=item).status_code == 201
    assert client.post("/api/items", json=item).status_code == 409


def test_update_not_found_and_empty_patch(client):
    assert client.patch("/api/items/55", json={"name": "Tea"}).status_code == 404
    assert client.patch("/api/items/55", json={}).status_code == 400


def test_put_replaces_optional_fields_and_requires_required_fields(client):
    item = {"name": "Tea", "barcode": "123", "quantity": 1, "price": 2.0}
    created = client.post("/api/items", json=item).get_json()

    assert client.put(f"/api/items/{created['id']}", json={"name": "New tea"}).status_code == 400
    response = client.put(
        f"/api/items/{created['id']}",
        json={"name": "New tea", "quantity": 3, "price": 5.0},
    )
    assert response.status_code == 200
    assert response.get_json()["barcode"] is None


def test_delete_not_found(client):
    assert client.delete("/api/items/55").status_code == 404


def test_lookup_by_barcode_normalizes_openfoodfacts_data(client):
    product = {
        "product_name": "Sample cereal",
        "code": "12345",
        "brands": "Example",
        "categories": "Breakfast cereals",
        "ingredients_text": "Oats",
        "image_url": "https://example.test/image.jpg",
    }
    response_body = json.dumps({"status": 1, "product": product}).encode()
    with patch.object(
        product_lookup,
        "urlopen",
        return_value=io.BytesIO(response_body),
    ) as mocked_urlopen:
        response = client.get("/api/products/lookup?barcode=12345")

    assert response.status_code == 200
    assert response.get_json() == {
        "name": "Sample cereal",
        "barcode": "12345",
        "brands": "Example",
        "category": "Breakfast cereals",
        "description": "Oats",
        "image_url": "https://example.test/image.jpg",
    }
    assert mocked_urlopen.called


def test_lookup_by_name_uses_first_search_result(client):
    response_body = json.dumps(
        {"products": [{"product_name": "Orange juice", "code": "999"}]}
    ).encode()
    with patch.object(product_lookup, "urlopen", return_value=io.BytesIO(response_body)):
        response = client.get("/api/products/lookup?name=orange+juice")
    assert response.status_code == 200
    assert response.get_json()["name"] == "Orange juice"


def test_lookup_requires_exactly_one_search_term(client):
    assert client.get("/api/products/lookup").status_code == 400
    assert (
        client.get("/api/products/lookup?barcode=123&name=tea").status_code
        == 400
    )


def test_lookup_not_found_and_provider_failure(client):
    missing_product = io.BytesIO(b'{"status": 0}')
    with patch.object(product_lookup, "urlopen", return_value=missing_product):
        assert client.get("/api/products/lookup?barcode=missing").status_code == 404

    with patch.object(
        product_lookup,
        "urlopen",
        side_effect=product_lookup.URLError("offline"),
    ):
        response = client.get("/api/products/lookup?barcode=123")
    assert response.status_code == 502
    assert "OpenFoodFacts lookup failed" in response.get_json()["error"]


def test_product_import_fetches_details_and_persists_item(client):
    product = {
        "name": "Imported cereal",
        "barcode": "654321",
        "category": "Breakfast cereals",
        "description": "Whole grain",
    }
    with patch.object(inventory_app, "lookup_product", return_value=product) as lookup:
        response = client.post(
            "/api/products/import",
            json={"barcode": "654321", "quantity": 6, "price": 4.25},
        )

    assert response.status_code == 201
    item = response.get_json()
    assert item["name"] == "Imported cereal"
    assert item["barcode"] == "654321"
    assert item["category"] == "Breakfast cereals"
    assert item["description"] == "Whole grain"
    assert item["quantity"] == 6
    assert item["price"] == 4.25
    assert client.get("/api/items").get_json() == [item]
    lookup.assert_called_once_with(barcode="654321", name=None, timeout=5)


def test_product_import_validates_input_and_handles_missing_product(client):
    invalid = client.post(
        "/api/products/import",
        json={"barcode": "654321", "quantity": -1, "price": 2.0},
    )
    assert invalid.status_code == 400

    with patch.object(inventory_app, "lookup_product", return_value=None):
        missing = client.post(
            "/api/products/import",
            json={"name": "Unknown", "quantity": 1, "price": 2.0},
        )
    assert missing.status_code == 404


def test_product_import_rejects_duplicate_barcode(client):
    product = {"name": "Cereal", "barcode": "654321"}
    with patch.object(inventory_app, "lookup_product", return_value=product):
        payload = {"barcode": "654321", "quantity": 1, "price": 2.0}
        assert client.post("/api/products/import", json=payload).status_code == 201
        assert client.post("/api/products/import", json=payload).status_code == 409


def test_cli_formats_and_routes_commands(capsys):
    import cli

    with patch.object(cli, "InventoryClient") as client_factory:
        client_factory.return_value.list_items.return_value = [{"id": 1}]
        assert cli.main(["list"]) == 0
    assert json.loads(capsys.readouterr().out) == [{"id": 1}]
    client_factory.return_value.list_items.assert_called_once_with()


def test_cli_create_passes_inventory_fields(capsys):
    import cli

    with patch.object(cli, "InventoryClient") as client_factory:
        client_factory.return_value.create_item.return_value = {"id": 4}
        result = cli.main(
            ["create", "--name", "Tea", "--quantity", "2", "--price", "1.5"]
        )
    assert result == 0
    client_factory.return_value.create_item.assert_called_once_with(
        {"name": "Tea", "quantity": 2, "price": 1.5}
    )
    assert json.loads(capsys.readouterr().out) == {"id": 4}


def test_cli_import_product_sends_import_command(capsys):
    import cli

    with patch.object(cli, "InventoryClient") as client_factory:
        client_factory.return_value.import_product.return_value = {"id": 8}
        result = cli.main(
            [
                "import-product",
                "--barcode",
                "654321",
                "--quantity",
                "4",
                "--price",
                "3.25",
            ]
        )
    assert result == 0
    client_factory.return_value.import_product.assert_called_once_with(
        barcode="654321", name=None, quantity=4, price=3.25
    )
    assert json.loads(capsys.readouterr().out) == {"id": 8}


def test_cli_reports_api_errors(capsys):
    import cli

    with patch.object(cli, "InventoryClient") as client_factory:
        client_factory.return_value.get_item.side_effect = cli.APIError("not found")
        assert cli.main(["get", "99"]) == 1
    assert "Error: not found" in capsys.readouterr().err
