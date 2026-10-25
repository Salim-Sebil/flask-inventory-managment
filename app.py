"""Flask REST API for retail inventory management."""

import math
import os
import sqlite3
from contextlib import closing

from flask import Flask, jsonify, request

from product_lookup import ProductLookupError, lookup_product


ITEM_FIELDS = {"name", "barcode", "category", "quantity", "price", "description"}
REQUIRED_ITEM_FIELDS = {"name", "quantity", "price"}


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        DATABASE=os.environ.get(
            "INVENTORY_DATABASE", os.path.join(app.instance_path, "inventory.sqlite3")
        ),
        OFF_TIMEOUT=5,
    )
    if test_config:
        app.config.update(test_config)

    os.makedirs(os.path.dirname(os.path.abspath(app.config["DATABASE"])), exist_ok=True)
    initialize_database(app.config["DATABASE"])

    @app.get("/api/items")
    def list_items():
        with closing(connect_database(app.config["DATABASE"])) as database:
            items = database.execute("SELECT * FROM items ORDER BY id").fetchall()
        return jsonify([dict(item) for item in items])

    @app.post("/api/items")
    def create_item():
        data = request.get_json(silent=True)
        error = validate_payload(data, partial=False)
        if error:
            return jsonify({"error": error}), 400

        item = {
            "barcode": None,
            "category": None,
            "description": None,
            **normalize_payload(data),
        }
        try:
            with closing(connect_database(app.config["DATABASE"])) as database:
                cursor = database.execute(
                    """
                    INSERT INTO items (name, barcode, category, quantity, price, description)
                    VALUES (:name, :barcode, :category, :quantity, :price, :description)
                    """,
                    item,
                )
                database.commit()
                created = database.execute(
                    "SELECT * FROM items WHERE id = ?", (cursor.lastrowid,)
                ).fetchone()
        except sqlite3.IntegrityError:
            return jsonify({"error": "An item with this barcode already exists"}), 409
        return jsonify(dict(created)), 201

    @app.get("/api/items/<int:item_id>")
    def get_item(item_id):
        with closing(connect_database(app.config["DATABASE"])) as database:
            item = database.execute(
                "SELECT * FROM items WHERE id = ?", (item_id,)
            ).fetchone()
        if item is None:
            return jsonify({"error": "Item not found"}), 404
        return jsonify(dict(item))

    @app.route("/api/items/<int:item_id>", methods=["PUT", "PATCH"])
    def update_item(item_id):
        data = request.get_json(silent=True)
        partial = request.method == "PATCH"
        error = validate_payload(data, partial=partial)
        if error:
            return jsonify({"error": error}), 400

        updates = normalize_payload(data)
        if not partial:
            for field in ("barcode", "category", "description"):
                updates.setdefault(field, None)
        try:
            with closing(connect_database(app.config["DATABASE"])) as database:
                existing = database.execute(
                    "SELECT * FROM items WHERE id = ?", (item_id,)
                ).fetchone()
                if existing is None:
                    return jsonify({"error": "Item not found"}), 404

                assignments = ", ".join(f"{field} = :{field}" for field in updates)
                updates["id"] = item_id
                database.execute(
                    f"UPDATE items SET {assignments} WHERE id = :id", updates
                )
                database.commit()
                updated = database.execute(
                    "SELECT * FROM items WHERE id = ?", (item_id,)
                ).fetchone()
        except sqlite3.IntegrityError:
            return jsonify({"error": "An item with this barcode already exists"}), 409
        return jsonify(dict(updated))

    @app.delete("/api/items/<int:item_id>")
    def delete_item(item_id):
        with closing(connect_database(app.config["DATABASE"])) as database:
            cursor = database.execute("DELETE FROM items WHERE id = ?", (item_id,))
            database.commit()
        if cursor.rowcount == 0:
            return jsonify({"error": "Item not found"}), 404
        return "", 204

    @app.get("/api/products/lookup")
    def product_lookup():
        barcode = request.args.get("barcode", "").strip()
        name = request.args.get("name", "").strip()
        if bool(barcode) == bool(name):
            return jsonify({"error": "Provide exactly one of barcode or name"}), 400

        try:
            product = lookup_product(
                barcode=barcode or None,
                name=name or None,
                timeout=app.config["OFF_TIMEOUT"],
            )
        except ProductLookupError as error:
            return jsonify({"error": str(error)}), 502
        if product is None:
            return jsonify({"error": "Product not found"}), 404
        return jsonify(product)

    @app.post("/api/products/import")
    def import_product():
        data = request.get_json(silent=True)
        allowed_fields = {"barcode", "name", "quantity", "price"}
        if not isinstance(data, dict):
            return jsonify({"error": "Request body must be a JSON object"}), 400
        if set(data) - allowed_fields:
            return jsonify({"error": "Only barcode, name, quantity, and price are allowed"}), 400

        barcode = data.get("barcode")
        name = data.get("name")
        if barcode is not None and not isinstance(barcode, str):
            return jsonify({"error": "barcode must be a string"}), 400
        if name is not None and not isinstance(name, str):
            return jsonify({"error": "name must be a string"}), 400
        barcode = barcode.strip() if barcode else None
        name = name.strip() if name else None
        if bool(barcode) == bool(name):
            return jsonify({"error": "Provide exactly one of barcode or name"}), 400

        required_data = {"quantity": data.get("quantity"), "price": data.get("price")}
        error = validate_payload(
            {"name": "Imported product", **required_data}, partial=False
        )
        if error:
            return jsonify({"error": error}), 400

        try:
            product = lookup_product(
                barcode=barcode,
                name=name,
                timeout=app.config["OFF_TIMEOUT"],
            )
        except ProductLookupError as error:
            return jsonify({"error": str(error)}), 502
        if product is None:
            return jsonify({"error": "Product not found"}), 404
        if not isinstance(product.get("name"), str) or not product["name"].strip():
            return jsonify({"error": "The external product has no usable name"}), 422

        item = {
            "name": product["name"],
            "barcode": product.get("barcode") or barcode,
            "category": product.get("category"),
            "quantity": required_data["quantity"],
            "price": required_data["price"],
            "description": product.get("description"),
        }
        item_error = validate_payload(item, partial=False)
        if item_error:
            return jsonify({"error": item_error}), 502
        item = normalize_payload(item)
        try:
            with closing(connect_database(app.config["DATABASE"])) as database:
                cursor = database.execute(
                    """
                    INSERT INTO items (name, barcode, category, quantity, price, description)
                    VALUES (:name, :barcode, :category, :quantity, :price, :description)
                    """,
                    item,
                )
                database.commit()
                created = database.execute(
                    "SELECT * FROM items WHERE id = ?", (cursor.lastrowid,)
                ).fetchone()
        except sqlite3.IntegrityError:
            return jsonify({"error": "An item with this barcode already exists"}), 409
        return jsonify(dict(created)), 201

    return app


def connect_database(database_path):
    database = sqlite3.connect(database_path)
    database.row_factory = sqlite3.Row
    return database


def initialize_database(database_path):
    with closing(connect_database(database_path)) as database:
        database.execute(
            """
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                barcode TEXT UNIQUE,
                category TEXT,
                quantity INTEGER NOT NULL CHECK (quantity >= 0),
                price REAL NOT NULL CHECK (price >= 0),
                description TEXT
            )
            """
        )
        database.commit()


def validate_payload(data, *, partial):
    if not isinstance(data, dict):
        return "Request body must be a JSON object"
    if not data:
        return "Provide at least one item field"

    unknown_fields = set(data) - ITEM_FIELDS
    if unknown_fields:
        return f"Unknown item field(s): {', '.join(sorted(unknown_fields))}"

    if not partial:
        missing_fields = REQUIRED_ITEM_FIELDS - data.keys()
        if missing_fields:
            return f"Missing required field(s): {', '.join(sorted(missing_fields))}"

    if "name" in data and (
        not isinstance(data["name"], str) or not data["name"].strip()
    ):
        return "name must be a non-empty string"
    if "barcode" in data and data["barcode"] is not None and not isinstance(
        data["barcode"], str
    ):
        return "barcode must be a string or null"
    for field in ("category", "description"):
        if field in data and data[field] is not None and not isinstance(data[field], str):
            return f"{field} must be a string or null"
    if "quantity" in data and (
        isinstance(data["quantity"], bool)
        or not isinstance(data["quantity"], int)
        or data["quantity"] < 0
        or data["quantity"] > 2**63 - 1
    ):
        return "quantity must be a non-negative 64-bit integer"
    if "price" in data and not valid_price(data["price"]):
        return "price must be a non-negative finite number"
    return None


def valid_price(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return False
    try:
        return math.isfinite(float(value))
    except OverflowError:
        return False


def normalize_payload(data):
    normalized = {}
    for field, value in data.items():
        if isinstance(value, str):
            value = value.strip()
        if field == "barcode" and value == "":
            value = None
        elif field in {"category", "description"} and value == "":
            value = None
        normalized[field] = float(value) if field == "price" else value
    return normalized


app = create_app()


if __name__ == "__main__":
    app.run()
