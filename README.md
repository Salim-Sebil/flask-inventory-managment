# Inventory Management API

A small Flask-based inventory service with a command-line client and product
lookup through the OpenFoodFacts API. Inventory records are stored in SQLite.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run the API:

```bash
python app.py
```

The database is created at `instance/inventory.sqlite3` by default. Set
`INVENTORY_DATABASE` to use a different SQLite file.

## REST API

All inventory endpoints use the `/api` prefix:

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/items` | List items |
| `POST` | `/api/items` | Create an item |
| `GET` | `/api/items/<id>` | View an item |
| `PUT` / `PATCH` | `/api/items/<id>` | Update an item |
| `DELETE` | `/api/items/<id>` | Delete an item |
| `GET` | `/api/products/lookup?barcode=<code>` | Look up a product barcode |
| `GET` | `/api/products/lookup?name=<name>` | Search products by name |
| `POST` | `/api/products/import` | Fetch an external product and create an inventory item |

Create an item with a JSON object containing `name`, `quantity`, and `price`.
`barcode`, `category`, and `description` are optional. Quantity must be a
non-negative integer, price a non-negative finite number, and barcodes are
unique.

```bash
curl -X POST http://127.0.0.1:5000/api/items \
  -H 'Content-Type: application/json' \
  -d '{"name":"Coffee","barcode":"012345","quantity":12,"price":4.5}'
```

Product lookups use the public OpenFoodFacts API. A missing product returns
`404`; provider/network failures return `502`.
Import requests require exactly one of `barcode` or `name`, plus an inventory
`quantity` and `price`. The product name, barcode, category, and description
are copied from OpenFoodFacts into the SQLite inventory.

```bash
curl -X POST http://127.0.0.1:5000/api/products/import \
  -H 'Content-Type: application/json' \
  -d '{"barcode":"012345","quantity":12,"price":4.5}'
```

## CLI

The CLI sends requests to the running API. Use `--base-url` if the API is not
running at the default address:

```bash
python cli.py list
python cli.py get 1
python cli.py create --name Coffee --barcode 012345 --quantity 12 --price 4.50
python cli.py update 1 --quantity 8
python cli.py delete 1
python cli.py lookup --barcode 012345
python cli.py lookup --name "orange juice"
python cli.py import-product --barcode 012345 --quantity 12 --price 4.50
python cli.py import-product --name "orange juice" --quantity 6 --price 3.25
```

## Tests

```bash
pytest
```

The OpenFoodFacts calls are mocked in the test suite, so tests do not depend on
network access.
