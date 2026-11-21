from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import uuid4

from integrations import (
    IntegrationError,
    create_checkout_preference,
    get_payment,
    integration_status,
    normalize_whatsapp_number,
    payment_configuration,
    send_whatsapp_template,
    validate_checkout_setup,
    verify_mercadopago_signature,
    whatsapp_configuration,
)


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = Path(os.environ.get("VERTICE_DATABASE", str(BASE_DIR / "vertice.db")))
ASSET_DIRECTORY = BASE_DIR / "assets"
CUSTOMER_WHATSAPP = os.environ.get("VERTICE_CUSTOMER_WHATSAPP", "5535910026290")
SELLER_WHATSAPP = os.environ.get("VERTICE_SELLER_WHATSAPP", "553591744878")
PRODUCT_IMAGE_FILES = {
    "monitor-lg-ultragear.jfif",
    "keyboard-white-rgb.jfif",
    "keyboard-compact-rgb.jfif",
    "keyboard-compact-white.jfif",
    "mouse-ergonomic.jfif",
    "mouse-wireless-g.jfif",
    "cable-hdmi-4k.jfif",
    "power-cable.jfif",
    "chair-ergonomic.webp",
}
SESSION_MAX_AGE = 8 * 60 * 60
PAYMENT_METHODS = {"pix": "Pix", "card": "Cartão", "boleto": "Boleto"}
PRODUCTS = [
    ("monitor-full-hd", "Monitor LG UltraGear 24”", "Monitores", "Monitor Full HD IPS de 24 polegadas com taxa de atualização de 144 Hz e resposta de 1 ms.", 89990, 92990, 12, "🖥️", "monitor", "/assets/monitor-lg-ultragear.jfif"),
    ("teclado-mecanico", "Teclado Mecânico Compacto RGB", "Teclados", "Teclado compacto com teclas responsivas e iluminação RGB para o dia a dia.", 24990, 15490, 24, "⌨️", "keyboard", "/assets/keyboard-compact-rgb.jfif"),
    ("mouse-sem-fio", "Mouse Sem Fio Precision", "Periféricos", "Mouse sem fio com sensor de alta precisão e controles laterais.", 11990, 6890, 35, "🖱️", "mouse", "/assets/mouse-wireless-g.jfif"),
    ("cabo-hdmi-2m", "Cabo HDMI 4K 2 m", "Cabos", "Cabo HDMI de alta velocidade com suporte a imagem 4K.", 3990, 1890, 80, "〰️", "hdmi", "/assets/cable-hdmi-4k.jfif"),
    ("cabo-forca-15m", "Cabo de Força 1,5 m", "Cabos", "Cabo de alimentação robusto, compatível com fontes e monitores.", 2990, 1290, 120, "🔌", "power", "/assets/power-cable.jfif"),
    ("cadeira-ergonomica", "Cadeira Ergonômica Office", "Escritório", "Cadeira com apoio lombar ajustável e braços acolchoados.", 119990, 87990, 8, "🪑", "chair", "/assets/chair-ergonomic.webp"),
    ("teclado-rgb-branco", "Teclado RGB Branco", "Teclados", "Teclado branco com teclas iluminadas em cores para compor seu setup.", 22990, 14190, 18, "⌨️", "keyboard", "/assets/keyboard-white-rgb.jfif"),
    ("teclado-compacto-branco", "Teclado Compacto Branco", "Teclados", "Teclado compacto branco com iluminação colorida e conexão com fio.", 19990, 12390, 16, "⌨️", "keyboard", "/assets/keyboard-compact-white.jfif"),
    ("mouse-ergonomico", "Mouse Ergonômico Precision", "Periféricos", "Mouse ergonômico com pegada confortável e botões laterais de navegação.", 10990, 6990, 23, "🖱️", "mouse", "/assets/mouse-ergonomic.jfif"),
]


def whatsapp_contacts() -> dict[str, str]:
    contacts = {
        "customer": CUSTOMER_WHATSAPP,
        "seller": SELLER_WHATSAPP,
    }
    if any(not re.fullmatch(r"\d{8,15}", number) for number in contacts.values()):
        raise RuntimeError("Os números de WhatsApp devem conter entre 8 e 15 dígitos.")
    return contacts


class InvalidOrder(ValueError):
    pass


class OutOfStock(ValueError):
    pass


class StoreError(Exception):
    def __init__(self, status: HTTPStatus, message: str) -> None:
        self.status = status
        self.message = message


def connect_database(path: Path = DATABASE_PATH) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


@contextmanager
def database_connection(path: Path = DATABASE_PATH):
    connection = connect_database(path)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database(path: Path = DATABASE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with database_connection(path) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS products (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                price_cents INTEGER NOT NULL CHECK (price_cents >= 0),
                unit_cost_cents INTEGER NOT NULL CHECK (unit_cost_cents >= 0),
                stock INTEGER NOT NULL CHECK (stock >= 0),
                icon TEXT NOT NULL,
                visual TEXT NOT NULL,
                image_path TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                customer_name TEXT NOT NULL,
                email TEXT NOT NULL,
                phone TEXT NOT NULL,
                postal_code TEXT NOT NULL,
                address TEXT NOT NULL,
                payment_method TEXT NOT NULL,
                total_cents INTEGER NOT NULL CHECK (total_cents >= 0),
                status TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                idempotency_key TEXT,
                payment_preference_id TEXT,
                payment_checkout_url TEXT,
                payment_id TEXT,
                payment_status TEXT NOT NULL DEFAULT 'demo',
                whatsapp_opt_in INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS order_items (
                order_id TEXT NOT NULL REFERENCES orders(id),
                product_id TEXT NOT NULL REFERENCES products(id),
                product_name TEXT NOT NULL,
                quantity INTEGER NOT NULL CHECK (quantity > 0),
                unit_price_cents INTEGER NOT NULL,
                unit_cost_cents INTEGER NOT NULL,
                PRIMARY KEY (order_id, product_id)
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS whatsapp_deliveries (
                order_id TEXT NOT NULL REFERENCES orders(id),
                recipient TEXT NOT NULL,
                event TEXT NOT NULL,
                status TEXT NOT NULL,
                provider_message_id TEXT,
                error TEXT,
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (order_id, recipient, event)
            );
            """
        )
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(products)").fetchall()
        }
        if "image_path" not in columns:
            connection.execute(
                "ALTER TABLE products ADD COLUMN image_path TEXT NOT NULL DEFAULT ''"
            )
        order_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(orders)").fetchall()
        }
        order_migrations = {
            "idempotency_key": "TEXT",
            "payment_preference_id": "TEXT",
            "payment_checkout_url": "TEXT",
            "payment_id": "TEXT",
            "payment_status": "TEXT NOT NULL DEFAULT 'demo'",
            "whatsapp_opt_in": "INTEGER NOT NULL DEFAULT 0",
        }
        for column, definition in order_migrations.items():
            if column not in order_columns:
                connection.execute(f"ALTER TABLE orders ADD COLUMN {column} {definition}")
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS orders_idempotency_key_unique "
            "ON orders(idempotency_key) WHERE idempotency_key IS NOT NULL"
        )
        connection.executemany(
            """
            INSERT INTO products
                (id, name, category, description, price_cents, unit_cost_cents, stock, icon, visual, image_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                image_path = excluded.image_path
            """,
            PRODUCTS,
        )
        connection.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES ('session_secret', ?)",
            (secrets.token_hex(32),),
        )


def list_products(path: Path = DATABASE_PATH) -> list[dict]:
    with database_connection(path) as connection:
        rows = connection.execute(
            """
            SELECT id, name, category, description, price_cents, stock, icon, visual, image_path
            FROM products ORDER BY CASE category
                WHEN 'Monitores' THEN 1 WHEN 'Teclados' THEN 2
                WHEN 'Periféricos' THEN 3 WHEN 'Cabos' THEN 4 ELSE 5 END, name
            """
        ).fetchall()
    return [dict(row) for row in rows]


def create_order(
    payload: object,
    path: Path = DATABASE_PATH,
    status: str = "Pedido recebido (simulação)",
    idempotency_key: str | None = None,
) -> str:
    if not isinstance(payload, dict):
        raise InvalidOrder("Os dados do pedido são inválidos.")

    customer = payload.get("customer")
    items = payload.get("items")
    payment_method = payload.get("payment_method")
    if not isinstance(customer, dict) or not isinstance(items, list) or not items:
        raise InvalidOrder("Informe seus dados e ao menos um produto.")
    if payment_method not in PAYMENT_METHODS:
        raise InvalidOrder("Selecione uma forma de pagamento válida.")
    if "whatsapp_opt_in" in payload and not isinstance(payload["whatsapp_opt_in"], bool):
        raise InvalidOrder("A autorização para mensagens de WhatsApp é inválida.")
    if idempotency_key is None:
        idempotency_key = payload.get("idempotency_key")
    if idempotency_key is None:
        idempotency_key = uuid4().hex
    elif not isinstance(idempotency_key, str) or not re.fullmatch(
        r"[a-fA-F0-9-]{32,36}", idempotency_key
    ):
        raise InvalidOrder("Identificador de tentativa de compra inválido.")

    fields = ("name", "email", "phone", "postal_code", "address")
    if any(not isinstance(customer.get(field), str) or not customer[field].strip() for field in fields):
        raise InvalidOrder("Preencha todos os dados de entrega.")
    clean_customer = {field: customer[field].strip()[:200] for field in fields}
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", clean_customer["email"]):
        raise InvalidOrder("Informe um e-mail válido.")

    quantities: dict[str, int] = {}
    if len(items) > 50:
        raise InvalidOrder("O carrinho contém itens demais.")
    for item in items:
        if not isinstance(item, dict):
            raise InvalidOrder("Um produto do carrinho é inválido.")
        product_id = item.get("product_id")
        quantity = item.get("quantity")
        if (
            not isinstance(product_id, str)
            or not isinstance(quantity, int)
            or isinstance(quantity, bool)
            or quantity < 1
            or quantity > 20
        ):
            raise InvalidOrder("A quantidade de um produto é inválida.")
        quantities[product_id] = quantities.get(product_id, 0) + quantity
        if quantities[product_id] > 20:
            raise InvalidOrder("A quantidade máxima por produto é 20.")

    order_id = uuid4().hex
    connection = connect_database(path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        previous = connection.execute(
            "SELECT id FROM orders WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if previous is not None:
            connection.commit()
            return previous["id"]
        order_lines = []
        total_cents = 0
        for product_id, quantity in quantities.items():
            product = connection.execute(
                """
                SELECT id, name, price_cents, unit_cost_cents, stock
                FROM products WHERE id = ?
                """,
                (product_id,),
            ).fetchone()
            if product is None:
                raise InvalidOrder("Um produto do carrinho não está disponível.")
            if product["stock"] < quantity:
                raise OutOfStock(
                    f"Estoque insuficiente para {product['name']}. Disponíveis: {product['stock']}."
                )
            total_cents += product["price_cents"] * quantity
            order_lines.append((product, quantity))

        connection.execute(
            """
            INSERT INTO orders
                (id, customer_name, email, phone, postal_code, address,
                 payment_method, total_cents, status, idempotency_key,
                 payment_status, whatsapp_opt_in)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_id,
                clean_customer["name"],
                clean_customer["email"],
                clean_customer["phone"],
                clean_customer["postal_code"],
                clean_customer["address"],
                PAYMENT_METHODS[payment_method],
                total_cents,
                status,
                idempotency_key,
                "demo" if "simulação" in status else "pending",
                int(payload.get("whatsapp_opt_in", False)),
            ),
        )
        for product, quantity in order_lines:
            connection.execute(
                "UPDATE products SET stock = stock - ? WHERE id = ?",
                (quantity, product["id"]),
            )
            connection.execute(
                """
                INSERT INTO order_items
                    (order_id, product_id, product_name, quantity, unit_price_cents, unit_cost_cents)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    product["id"],
                    product["name"],
                    quantity,
                    product["price_cents"],
                    product["unit_cost_cents"],
                ),
            )
        connection.commit()
        return order_id
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def get_order(order_id: str, path: Path = DATABASE_PATH) -> dict | None:
    with database_connection(path) as connection:
        order = connection.execute(
            """
            SELECT id, payment_method, total_cents, status, created_at,
                   payment_status
            FROM orders WHERE id = ?
            """,
            (order_id,),
        ).fetchone()
        if order is None:
            return None
        items = connection.execute(
            """
            SELECT product_id, product_name, quantity, unit_price_cents
            FROM order_items WHERE order_id = ? ORDER BY product_name
            """,
            (order_id,),
        ).fetchall()
    return {
        "order": dict(order),
        "items": [dict(item) for item in items],
        "whatsapp": whatsapp_contacts(),
    }


def set_checkout_preference(
    order_id: str, preference: dict[str, str], path: Path = DATABASE_PATH
) -> None:
    with database_connection(path) as connection:
        connection.execute(
            """
            UPDATE orders
            SET payment_preference_id = ?, payment_checkout_url = ?
            WHERE id = ? AND payment_status = 'pending'
            """,
            (preference["id"], preference["checkout_url"], order_id),
        )


def apply_provider_payment(payment: dict, path: Path = DATABASE_PATH) -> dict:
    payment_id = str(payment.get("id", ""))
    order_id = payment.get("external_reference")
    if not re.fullmatch(r"\d{1,30}", payment_id) or not isinstance(order_id, str):
        raise IntegrationError("A notificação do pagamento não identifica um pedido válido.")

    provider_status = payment.get("status")
    if not isinstance(provider_status, str):
        raise IntegrationError("O Mercado Pago não informou o estado do pagamento.")
    if provider_status == "approved":
        try:
            paid_decimal = Decimal(str(payment.get("transaction_amount"))) * 100
        except (InvalidOperation, TypeError, ValueError) as error:
            raise IntegrationError("O valor confirmado pelo Mercado Pago é inválido.") from error
        if not paid_decimal.is_finite() or paid_decimal != paid_decimal.to_integral_value():
            raise IntegrationError("O valor confirmado pelo Mercado Pago é inválido.")
        paid_amount = int(paid_decimal)
        with database_connection(path) as connection:
            order = connection.execute(
                "SELECT total_cents FROM orders WHERE id = ?", (order_id,)
            ).fetchone()
        if order is None or payment.get("currency_id") != "BRL" or paid_amount != order["total_cents"]:
            raise IntegrationError("O pagamento não corresponde ao valor e à moeda do pedido.")

    status_labels = {
        "approved": "Pagamento confirmado",
        "pending": "Aguardando pagamento",
        "in_process": "Pagamento em análise",
        "rejected": "Pagamento não aprovado",
        "cancelled": "Pagamento cancelado",
        "refunded": "Pagamento reembolsado",
        "charged_back": "Pagamento contestado",
    }
    label = status_labels.get(provider_status, "Pagamento em atualização")
    with database_connection(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        order = connection.execute(
            "SELECT payment_status FROM orders WHERE id = ?", (order_id,)
        ).fetchone()
        if order is None:
            raise IntegrationError("O pagamento não corresponde a um pedido registrado.")
        if order["payment_status"] != "approved":
            connection.execute(
                """
                UPDATE orders SET payment_status = ?, payment_id = ?, status = ?
                WHERE id = ?
                """,
                (provider_status, payment_id, label, order_id),
            )
    if provider_status == "approved":
        send_whatsapp_order_messages(order_id, "paid", path)
    return {"order_id": order_id, "payment_status": provider_status, "status": label}


def send_whatsapp_order_messages(
    order_id: str, event: str, path: Path = DATABASE_PATH
) -> list[dict[str, str]]:
    config = whatsapp_configuration()
    if not config["configured"]:
        return [{"recipient": "all", "status": "not_configured"}]
    with database_connection(path) as connection:
        order = connection.execute(
            """
            SELECT customer_name, phone, total_cents, payment_method,
                   whatsapp_opt_in, status
            FROM orders WHERE id = ?
            """,
            (order_id,),
        ).fetchone()
        if order is None:
            raise IntegrationError("O pedido para notificação não foi encontrado.")
        items = connection.execute(
            """
            SELECT product_name, quantity FROM order_items
            WHERE order_id = ? ORDER BY product_name
            """,
            (order_id,),
        ).fetchall()
    contacts = whatsapp_contacts()
    item_summary = ", ".join(
        f"{item['product_name']} x{item['quantity']}" for item in items
    )[:900]
    payment_label = (
        "Pagamento confirmado" if event == "paid" else "Pedido criado; pagamento pendente"
    )
    amount = f"R$ {order['total_cents'] // 100},{order['total_cents'] % 100:02d}"
    destinations = [
        (
            "seller",
            contacts["seller"],
            os.environ["VERTICE_WHATSAPP_SELLER_TEMPLATE"],
            [
                order_id,
                order["customer_name"][:120],
                item_summary,
                amount,
                order["payment_method"],
                payment_label,
            ],
        )
    ]
    if order["whatsapp_opt_in"]:
        destinations.append(
            (
                "customer",
                normalize_whatsapp_number(order["phone"]),
                os.environ["VERTICE_WHATSAPP_CUSTOMER_TEMPLATE"],
                [order_id, payment_label, amount, order["payment_method"]],
            )
        )

    results = []
    for recipient_kind, phone, template, parameters in destinations:
        claim = connect_database(path)
        try:
            claim.execute("BEGIN IMMEDIATE")
            delivery = claim.execute(
                """
                SELECT status FROM whatsapp_deliveries
                WHERE order_id = ? AND recipient = ? AND event = ?
                """,
                (order_id, phone, event),
            ).fetchone()
            if delivery is not None and delivery["status"] in {"sending", "sent"}:
                claim.commit()
                results.append({"recipient": recipient_kind, "status": delivery["status"]})
                continue
            claim.execute(
                """
                INSERT INTO whatsapp_deliveries
                    (order_id, recipient, event, status)
                VALUES (?, ?, ?, 'sending')
                ON CONFLICT(order_id, recipient, event)
                DO UPDATE SET status = 'sending', error = NULL,
                              updated_at = datetime('now')
                """,
                (order_id, phone, event),
            )
            claim.commit()
        except Exception:
            claim.rollback()
            raise
        finally:
            claim.close()

        try:
            message_id = send_whatsapp_template(
                os.environ["VERTICE_WHATSAPP_PHONE_NUMBER_ID"],
                phone,
                template,
                parameters,
            )
        except IntegrationError as error:
            with database_connection(path) as connection:
                connection.execute(
                    """
                    UPDATE whatsapp_deliveries
                    SET status = 'failed', error = ?, updated_at = datetime('now')
                    WHERE order_id = ? AND recipient = ? AND event = ?
                    """,
                    (str(error)[:300], order_id, phone, event),
                )
            print(f"[Vértice] Falha de WhatsApp para {recipient_kind}: {error}")
            results.append({"recipient": recipient_kind, "status": "failed"})
        else:
            with database_connection(path) as connection:
                connection.execute(
                    """
                    UPDATE whatsapp_deliveries
                    SET status = 'sent', provider_message_id = ?,
                        error = NULL, updated_at = datetime('now')
                    WHERE order_id = ? AND recipient = ? AND event = ?
                    """,
                    (message_id, order_id, phone, event),
                )
            results.append({"recipient": recipient_kind, "status": "sent"})
    return results


class StoreRequestHandler(BaseHTTPRequestHandler):
    server_version = "VerticeStore/1.0"

    def do_GET(self) -> None:
        parsed_url = urlsplit(self.path)
        path = unquote(parsed_url.path)
        if path == "/api/products":
            self.send_json(HTTPStatus.OK, {"products": list_products()})
            return
        if path == "/api/integrations/status":
            try:
                status = integration_status()
            except IntegrationError as error:
                self.send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(error)})
            else:
                self.send_json(HTTPStatus.OK, status)
            return
        if path.startswith("/api/orders/"):
            order_id = path.removeprefix("/api/orders/")
            payment_id = parse_qs(parsed_url.query).get("payment_id", [""])[0]
            if payment_id:
                try:
                    payment = get_payment(payment_id)
                    if payment.get("external_reference") != order_id:
                        raise IntegrationError("O pagamento pertence a outro pedido.")
                    result = apply_provider_payment(payment)
                except IntegrationError as error:
                    self.send_json(HTTPStatus.BAD_GATEWAY, {"error": str(error)})
                    return
            order = get_order(order_id)
            if order is None:
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "Pedido não encontrado."})
            else:
                self.send_json(HTTPStatus.OK, order)
            return
        if path == "/api/webhooks/mercadopago":
            self.send_json(
                HTTPStatus.METHOD_NOT_ALLOWED,
                {"error": "Use POST para notificações de pagamento."},
            )
            return
        if path == "/api/finance/data":
            if not self.has_finance_session():
                self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "Acesso restrito."})
                return
            self.send_json(HTTPStatus.OK, self.get_finance_data())
            return
        if path.startswith("/api/"):
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Recurso não encontrado."})
            return

        static_files = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/index.html": ("index.html", "text/html; charset=utf-8"),
            "/styles.css": ("styles.css", "text/css; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
        }
        if path.startswith("/assets/"):
            filename = path.removeprefix("/assets/")
            asset_path = (ASSET_DIRECTORY / filename).resolve()
            if (
                filename not in PRODUCT_IMAGE_FILES
                or asset_path.parent != ASSET_DIRECTORY.resolve()
                or not asset_path.is_file()
            ):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            content = asset_path.read_bytes()
            content_type = (
                "image/webp"
                if asset_path.suffix.lower() == ".webp"
                else "image/jpeg"
            )
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(content)
            return
        asset = static_files.get(path)
        if asset is None and (path.startswith("/produto/") or path.startswith("/pedido/") or path == "/empresa"):
            asset = static_files["/"]
        if asset is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content = (BASE_DIR / asset[0]).read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", asset[1])
        self.send_header("Content-Length", str(len(content)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path not in {
            "/api/orders",
            "/api/finance/login",
            "/api/finance/logout",
            "/api/webhooks/mercadopago",
        }:
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Recurso não encontrado."})
            return
        try:
            payload = self.read_json()
        except (ValueError, UnicodeDecodeError):
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "O corpo da solicitação não é um JSON válido."})
            return

        if path == "/api/webhooks/mercadopago":
            self.handle_mercadopago_webhook(payload)
            return

        if path == "/api/orders":
            try:
                config = payment_configuration()
                if config["configured"]:
                    config = validate_checkout_setup()
                idempotency_key = (
                    payload.get("idempotency_key")
                    if isinstance(payload, dict)
                    else None
                )
                order_id = create_order(
                    payload,
                    status=(
                        "Aguardando pagamento"
                        if config["configured"]
                        else "Pedido recebido (simulação)"
                    ),
                    idempotency_key=idempotency_key,
                )
                checkout_url = None
                notifications = []
                if config["configured"]:
                    with database_connection() as connection:
                        saved_preference = connection.execute(
                            """
                            SELECT payment_preference_id, payment_checkout_url
                            FROM orders WHERE id = ?
                            """,
                            (order_id,),
                        ).fetchone()
                    if saved_preference and saved_preference["payment_checkout_url"]:
                        checkout_url = saved_preference["payment_checkout_url"]
                    else:
                        order_items = self.get_order_items(order_id)
                        preference = create_checkout_preference(
                            order_id,
                            payload["customer"]["email"].strip(),
                            order_items,
                            payload["payment_method"],
                        )
                        set_checkout_preference(order_id, preference)
                        checkout_url = preference["checkout_url"]
                    notifications = send_whatsapp_order_messages(order_id, "created")
                else:
                    config = {"mode": "demo"}
            except OutOfStock as error:
                self.send_json(HTTPStatus.CONFLICT, {"error": str(error)})
            except InvalidOrder as error:
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            except IntegrationError as error:
                self.send_json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(error)})
            else:
                self.send_json(
                    HTTPStatus.CREATED,
                    {
                        "order_id": order_id,
                        "checkout_url": checkout_url,
                        "payment_mode": config["mode"],
                        "whatsapp": notifications,
                    },
                )
            return

        if path == "/api/finance/logout":
            self.send_json(
                HTTPStatus.OK,
                {"authenticated": False},
                cookie="vertice_finance=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict",
            )
            return

        password = os.environ.get("VERTICE_FINANCE_PASSWORD")
        if not password:
            self.send_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"error": "A área financeira não foi configurada. Defina VERTICE_FINANCE_PASSWORD no ambiente."},
            )
            return
        supplied = payload.get("password") if isinstance(payload, dict) else None
        if not isinstance(supplied, str) or not hmac.compare_digest(supplied, password):
            self.send_json(HTTPStatus.UNAUTHORIZED, {"error": "Senha incorreta."})
            return
        self.send_json(
            HTTPStatus.OK,
            {"authenticated": True},
            cookie=self.create_finance_cookie(),
        )

    def read_json(self) -> object:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise ValueError("Content-Length inválido.") from error
        if length < 1 or length > 65536:
            raise ValueError("Tamanho de solicitação inválido.")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def get_order_items(self, order_id: str) -> list[dict]:
        with database_connection() as connection:
            items = connection.execute(
                """
                SELECT product_id, product_name, quantity, unit_price_cents
                FROM order_items WHERE order_id = ? ORDER BY product_name
                """,
                (order_id,),
            ).fetchall()
        return [dict(item) for item in items]

    def handle_mercadopago_webhook(self, payload: object) -> None:
        secret = os.environ.get("VERTICE_MERCADOPAGO_WEBHOOK_SECRET", "").strip()
        token = os.environ.get("VERTICE_MERCADOPAGO_ACCESS_TOKEN", "").strip()
        if not secret or not token:
            self.send_json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {"error": "Webhook do Mercado Pago não configurado."},
            )
            return
        parsed_url = urlsplit(self.path)
        query = parse_qs(parsed_url.query)
        payment_id = query.get("data.id", [""])[0]
        if not payment_id and isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, dict):
                payment_id = str(data.get("id", ""))
        signature = self.headers.get("x-signature", "")
        request_id = self.headers.get("x-request-id", "")
        if not verify_mercadopago_signature(
            payment_id, request_id, signature, secret
        ):
            self.send_json(
                HTTPStatus.UNAUTHORIZED,
                {"error": "Assinatura do webhook inválida."},
            )
            return
        try:
            payment = get_payment(payment_id)
            result = apply_provider_payment(payment)
        except IntegrationError as error:
            self.send_json(HTTPStatus.BAD_GATEWAY, {"error": str(error)})
            return
        self.send_json(HTTPStatus.OK, {"received": True, **result})

    def send_json(
        self,
        status: HTTPStatus,
        payload: dict,
        cookie: str | None = None,
    ) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(content)

    def session_secret(self) -> bytes:
        with database_connection() as connection:
            secret = connection.execute(
                "SELECT value FROM settings WHERE key = 'session_secret'"
            ).fetchone()
        if secret is None:
            raise RuntimeError("Segredo da sessão financeira não foi inicializado.")
        return secret["value"].encode("utf-8")

    def create_finance_cookie(self) -> str:
        expires = int(time.time()) + SESSION_MAX_AGE
        payload = str(expires)
        signature = hmac.new(self.session_secret(), payload.encode("ascii"), hashlib.sha256).hexdigest()
        return (
            f"vertice_finance={payload}.{signature}; Path=/; Max-Age={SESSION_MAX_AGE}; "
            "HttpOnly; SameSite=Strict"
        )

    def has_finance_session(self) -> bool:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            token = cookie["vertice_finance"].value
            expiry_text, signature = token.split(".", 1)
            expiry = int(expiry_text)
        except (KeyError, ValueError):
            return False
        if expiry < int(time.time()) or expiry > int(time.time()) + SESSION_MAX_AGE:
            return False
        expected = hmac.new(
            self.session_secret(), expiry_text.encode("ascii"), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(signature, expected)

    def get_finance_data(self) -> dict:
        with database_connection() as connection:
            products = connection.execute(
                """
                SELECT p.id, p.name, p.price_cents, p.unit_cost_cents, p.stock,
                       COALESCE(
                           SUM(CASE WHEN o.id IS NOT NULL THEN i.quantity ELSE 0 END),
                           0
                       ) AS units_sold
                FROM products p
                LEFT JOIN order_items i ON i.product_id = p.id
                LEFT JOIN orders o
                    ON o.id = i.order_id AND o.payment_status IN ('approved', 'demo')
                GROUP BY p.id ORDER BY p.name
                """
            ).fetchall()
        report = []
        for product in products:
            units = product["units_sold"]
            revenue = product["price_cents"] * units
            cost = product["unit_cost_cents"] * units
            report.append(
                {
                    "id": product["id"],
                    "name": product["name"],
                    "price_cents": product["price_cents"],
                    "unit_cost_cents": product["unit_cost_cents"],
                    "stock": product["stock"],
                    "units_sold": units,
                    "revenue_cents": revenue,
                    "cost_cents": cost,
                    "profit_cents": revenue - cost,
                }
            )
        return {"products": report, "data_is_hypothetical": True}

    def log_message(self, format: str, *args: object) -> None:
        print(f"[Vértice] {self.address_string()} - {format % args}")


def server_bind_settings() -> tuple[str, int]:
    host = os.environ.get(
        "VERTICE_HOST",
        "0.0.0.0" if os.environ.get("PORT") else "127.0.0.1",
    )
    port = int(os.environ.get("PORT", os.environ.get("VERTICE_PORT", "8000")))
    return host, port


def main() -> None:
    initialize_database()
    host, port = server_bind_settings()
    server = ThreadingHTTPServer((host, port), StoreRequestHandler)
    print(f"Vértice Loja disponível em http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor encerrado.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
