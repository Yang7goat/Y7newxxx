import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import app


class OrderTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "store.db"
        app.initialize_database(self.database_path)
        with app.database_connection(self.database_path) as connection:
            connection.execute("UPDATE products SET stock = 1 WHERE id = 'cabo-hdmi-2m'")

    def tearDown(self):
        self.temp_dir.cleanup()

    def payload(self):
        return {
            "customer": {
                "name": "Pessoa de Teste",
                "email": "teste@example.com",
                "phone": "11999999999",
                "postal_code": "01000-000",
                "address": "Rua de Teste, 10",
            },
            "items": [{"product_id": "cabo-hdmi-2m", "quantity": 1}],
            "payment_method": "pix",
        }

    def test_server_uses_render_port_and_keeps_local_defaults(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(app.server_bind_settings(), ("127.0.0.1", 8000))
        with patch.dict("os.environ", {"PORT": "10000"}, clear=True):
            self.assertEqual(app.server_bind_settings(), ("0.0.0.0", 10000))

    def test_order_uses_server_price_and_reduces_stock(self):
        order_id = app.create_order(self.payload(), self.database_path)
        order = app.get_order(order_id, self.database_path)
        self.assertEqual(order["order"]["total_cents"], 3990)
        self.assertEqual(order["items"][0]["product_name"], "Cabo HDMI 4K 2 m")
        self.assertEqual(
            next(product["stock"] for product in app.list_products(self.database_path) if product["id"] == "cabo-hdmi-2m"),
            0,
        )

    def test_catalog_includes_product_photos_and_additional_variants(self):
        catalog = app.list_products(self.database_path)
        products_with_photos = [product for product in catalog if product["image_path"]]
        self.assertEqual(len(products_with_photos), 9)
        self.assertTrue(any(product["id"] == "teclado-rgb-branco" for product in catalog))
        self.assertTrue(any(product["id"] == "mouse-ergonomico" for product in catalog))
        images_by_product = {product["id"]: product["image_path"] for product in catalog}
        self.assertEqual(images_by_product["cabo-forca-15m"], "/assets/power-cable.jfif")
        self.assertEqual(images_by_product["cadeira-ergonomica"], "/assets/chair-ergonomic.webp")
        for product in products_with_photos:
            asset = app.BASE_DIR / "assets" / product["image_path"].removeprefix("/assets/")
            self.assertTrue(asset.is_file(), product["image_path"])

    def test_concurrent_orders_cannot_sell_the_last_unit_twice(self):
        barrier = threading.Barrier(2)
        outcomes = []
        lock = threading.Lock()

        def place_order():
            barrier.wait()
            try:
                result = ("created", app.create_order(self.payload(), self.database_path))
            except app.OutOfStock:
                result = ("out_of_stock", None)
            with lock:
                outcomes.append(result)

        threads = [threading.Thread(target=place_order) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertCountEqual([status for status, _ in outcomes], ["created", "out_of_stock"])
        self.assertEqual(
            next(product["stock"] for product in app.list_products(self.database_path) if product["id"] == "cabo-hdmi-2m"),
            0,
        )

    def test_invalid_payment_does_not_change_stock(self):
        payload = self.payload()
        payload["payment_method"] = "crypto"
        with self.assertRaises(app.InvalidOrder):
            app.create_order(payload, self.database_path)
        self.assertEqual(
            next(product["stock"] for product in app.list_products(self.database_path) if product["id"] == "cabo-hdmi-2m"),
            1,
        )

    def test_idempotent_order_does_not_reserve_stock_twice(self):
        payload = self.payload()
        payload["idempotency_key"] = "a" * 32
        first_order = app.create_order(
            payload, self.database_path, status="Aguardando pagamento"
        )
        second_order = app.create_order(
            payload, self.database_path, status="Aguardando pagamento"
        )
        self.assertEqual(first_order, second_order)
        self.assertEqual(
            next(product["stock"] for product in app.list_products(self.database_path) if product["id"] == "cabo-hdmi-2m"),
            0,
        )

    def test_approved_payment_updates_status_only_for_matching_amount(self):
        order_id = app.create_order(
            self.payload(), self.database_path, status="Aguardando pagamento"
        )
        payment = {
            "id": 123456,
            "external_reference": order_id,
            "status": "approved",
            "transaction_amount": 39.9,
            "currency_id": "BRL",
        }
        with patch.dict("os.environ", {}, clear=True):
            result = app.apply_provider_payment(payment, self.database_path)
        self.assertEqual(result["payment_status"], "approved")
        self.assertEqual(app.get_order(order_id, self.database_path)["order"]["status"], "Pagamento confirmado")

        invalid_payment = {**payment, "id": 123457, "transaction_amount": 1.0}
        with self.assertRaises(app.IntegrationError):
            app.apply_provider_payment(invalid_payment, self.database_path)

    def test_finance_report_excludes_pending_orders(self):
        with app.database_connection(self.database_path) as connection:
            connection.execute(
                "UPDATE products SET stock = 3 WHERE id = 'cabo-hdmi-2m'"
            )
        app.create_order(self.payload(), self.database_path)
        app.create_order(
            self.payload(), self.database_path, status="Aguardando pagamento"
        )
        database_connection = app.database_connection
        with patch(
            "app.database_connection",
            side_effect=lambda: database_connection(self.database_path),
        ):
            handler = object.__new__(app.StoreRequestHandler)
            report = handler.get_finance_data()
        cable = next(
            product
            for product in report["products"]
            if product["id"] == "cabo-hdmi-2m"
        )
        self.assertEqual(cable["units_sold"], 1)

    def test_whatsapp_notifications_require_opt_in_and_are_idempotent(self):
        payload = self.payload()
        payload["whatsapp_opt_in"] = True
        order_id = app.create_order(
            payload, self.database_path, status="Aguardando pagamento"
        )
        whatsapp_env = {
            "VERTICE_WHATSAPP_ACCESS_TOKEN": "test-token",
            "VERTICE_WHATSAPP_PHONE_NUMBER_ID": "123456789",
            "VERTICE_WHATSAPP_CUSTOMER_TEMPLATE": "vertice_customer_update",
            "VERTICE_WHATSAPP_SELLER_TEMPLATE": "vertice_seller_update",
            "VERTICE_WHATSAPP_SEND_ENABLED": "true",
        }
        with patch.dict("os.environ", whatsapp_env, clear=True):
            with patch("app.send_whatsapp_template", return_value="wamid.test") as sender:
                first = app.send_whatsapp_order_messages(
                    order_id, "created", self.database_path
                )
                second = app.send_whatsapp_order_messages(
                    order_id, "created", self.database_path
                )
        self.assertEqual(len(first), 2)
        self.assertEqual(len(second), 2)
        self.assertEqual(sender.call_count, 2)


if __name__ == "__main__":
    unittest.main()
