import hashlib
import hmac
import os
import unittest
from unittest.mock import patch

import integrations


class IntegrationTests(unittest.TestCase):
    def test_test_payment_creates_sandbox_checkout_with_public_webhook(self):
        environment = {
            "VERTICE_MERCADOPAGO_MODE": "test",
            "VERTICE_MERCADOPAGO_ACCESS_TOKEN": "TEST-local-token",
            "VERTICE_PUBLIC_BASE_URL": "https://shop.example.test",
        }
        items = [
            {
                "product_id": "cabo-hdmi-2m",
                "product_name": "Cabo HDMI",
                "quantity": 2,
                "unit_price_cents": 3990,
            }
        ]
        with patch.dict(os.environ, environment, clear=True):
            with patch(
                "integrations._request_json",
                return_value={
                    "id": "preference-123",
                    "sandbox_init_point": "https://sandbox.mercadopago.com/checkout",
                    "init_point": "https://www.mercadopago.com/checkout",
                },
            ) as request:
                result = integrations.create_checkout_preference(
                    "a" * 32, "buyer@example.com", items, "pix"
                )
        self.assertEqual(
            request.call_args.args[2]["Authorization"],
            "Bearer TEST-local-token",
        )
        request_payload = request.call_args.args[1]
        self.assertEqual(result["id"], "preference-123")
        self.assertTrue(result["checkout_url"].startswith("https://sandbox."))
        self.assertEqual(request_payload["external_reference"], "a" * 32)
        self.assertEqual(request_payload["items"][0]["unit_price"], 39.9)
        self.assertEqual(
            request_payload["notification_url"],
            "https://shop.example.test/api/webhooks/mercadopago",
        )
        self.assertTrue(request_payload["expires"])
        self.assertIn(
            {"id": "ticket"},
            request_payload["payment_methods"]["excluded_payment_types"],
        )
        self.assertNotIn(
            {"id": "bank_transfer"},
            request_payload["payment_methods"]["excluded_payment_types"],
        )

    def test_live_checkout_refuses_localhost_callback(self):
        environment = {
            "VERTICE_MERCADOPAGO_MODE": "test",
            "VERTICE_MERCADOPAGO_ACCESS_TOKEN": "TEST-local-token",
            "VERTICE_PUBLIC_BASE_URL": "http://127.0.0.1:8000",
        }
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaises(integrations.IntegrationError):
                integrations.validate_checkout_setup()

    def test_live_payments_require_explicit_enablement(self):
        environment = {
            "VERTICE_MERCADOPAGO_MODE": "production",
            "VERTICE_MERCADOPAGO_ACCESS_TOKEN": "APP_USR-local-token",
            "VERTICE_PUBLIC_BASE_URL": "https://shop.example.test",
            "VERTICE_MERCADOPAGO_WEBHOOK_SECRET": "webhook-secret",
        }
        with patch.dict(os.environ, environment, clear=True):
            with self.assertRaisesRegex(integrations.IntegrationError, "bloqueados"):
                integrations.validate_checkout_setup()

    def test_mercadopago_webhook_signature_matches_expected_manifest(self):
        payment_id = "123456789"
        request_id = "request-1"
        timestamp = "1700000000"
        secret = "local-webhook-secret"
        manifest = f"id:{payment_id};request-id:{request_id};ts:{timestamp};"
        digest = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
        signature = f"ts={timestamp},v1={digest}"
        self.assertTrue(
            integrations.verify_mercadopago_signature(
                payment_id, request_id, signature, secret
            )
        )
        self.assertFalse(
            integrations.verify_mercadopago_signature(
                payment_id, request_id, signature, "wrong-secret"
            )
        )

    def test_brazilian_local_phone_is_normalized_for_cloud_api(self):
        self.assertEqual(
            integrations.normalize_whatsapp_number("(35) 99123-4567"),
            "5535991234567",
        )
        with self.assertRaises(integrations.IntegrationError):
            integrations.normalize_whatsapp_number("123")


if __name__ == "__main__":
    unittest.main()
