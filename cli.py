"""Command-line client for the inventory REST API."""

import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class APIError(Exception):
    """Raised when the inventory API returns an error."""


class InventoryClient:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")

    def _request(self, path, *, method="GET", payload=None):
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            with urlopen(request, timeout=10) as response:
                content = response.read()
        except HTTPError as error:
            content = error.read()
            try:
                message = json.loads(content.decode("utf-8")).get("error", str(error))
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                message = str(error)
            raise APIError(message) from error
        except (URLError, TimeoutError) as error:
            raise APIError(f"Could not reach inventory API: {error}") from error
        if not content:
            return None
        return json.loads(content.decode("utf-8"))

    def list_items(self):
        return self._request("/api/items")

    def get_item(self, item_id):
        return self._request(f"/api/items/{item_id}")

    def create_item(self, payload):
        return self._request("/api/items", method="POST", payload=payload)

    def update_item(self, item_id, payload):
        return self._request(f"/api/items/{item_id}", method="PATCH", payload=payload)

    def delete_item(self, item_id):
        self._request(f"/api/items/{item_id}", method="DELETE")

    def lookup_product(self, *, barcode=None, name=None):
        query = urlencode({"barcode": barcode} if barcode else {"name": name})
        return self._request(f"/api/products/lookup?{query}")

    def import_product(self, *, barcode=None, name=None, quantity, price):
        payload = {"quantity": quantity, "price": price}
        payload["barcode" if barcode else "name"] = barcode or name
        return self._request("/api/products/import", method="POST", payload=payload)


def build_parser():
    parser = argparse.ArgumentParser(description="Manage inventory through the REST API")
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="list all inventory items")

    get_command = commands.add_parser("get", help="view one inventory item")
    get_command.add_argument("item_id", type=int)

    create_command = commands.add_parser("create", help="add an inventory item")
    _add_item_arguments(create_command, include_required=True)

    update_command = commands.add_parser("update", help="edit an inventory item")
    update_command.add_argument("item_id", type=int)
    _add_item_arguments(update_command, include_required=False)

    delete_command = commands.add_parser("delete", help="delete an inventory item")
    delete_command.add_argument("item_id", type=int)

    lookup_command = commands.add_parser("lookup", help="search OpenFoodFacts")
    lookup_group = lookup_command.add_mutually_exclusive_group(required=True)
    lookup_group.add_argument("--barcode")
    lookup_group.add_argument("--name")

    import_command = commands.add_parser(
        "import-product",
        help="fetch product details from OpenFoodFacts and add the product to inventory",
    )
    import_group = import_command.add_mutually_exclusive_group(required=True)
    import_group.add_argument("--barcode")
    import_group.add_argument("--name")
    import_command.add_argument("--quantity", type=int, required=True)
    import_command.add_argument("--price", type=float, required=True)
    return parser


def _add_item_arguments(parser, *, include_required):
    parser.add_argument("--name", required=include_required)
    parser.add_argument("--barcode")
    parser.add_argument("--category")
    parser.add_argument("--quantity", type=int, required=include_required)
    parser.add_argument("--price", type=float, required=include_required)
    parser.add_argument("--description")


def main(argv=None):
    args = build_parser().parse_args(argv)
    client = InventoryClient(args.base_url)
    try:
        if args.command == "list":
            result = client.list_items()
        elif args.command == "get":
            result = client.get_item(args.item_id)
        elif args.command == "create":
            result = client.create_item(_item_payload(args))
        elif args.command == "update":
            payload = _item_payload(args)
            if not payload:
                raise APIError("Provide at least one item field to update")
            result = client.update_item(args.item_id, payload)
        elif args.command == "delete":
            client.delete_item(args.item_id)
            result = {"message": "Item deleted"}
        elif args.command == "import-product":
            result = client.import_product(
                barcode=args.barcode,
                name=args.name,
                quantity=args.quantity,
                price=args.price,
            )
        else:
            result = client.lookup_product(barcode=args.barcode, name=args.name)
    except APIError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


def _item_payload(args):
    fields = ("name", "barcode", "category", "quantity", "price", "description")
    return {
        field: getattr(args, field)
        for field in fields
        if getattr(args, field) is not None
    }


if __name__ == "__main__":
    raise SystemExit(main())
