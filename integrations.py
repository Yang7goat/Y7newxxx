from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal
from datetime import datetime, timedelta, timezone


class IntegrationError(RuntimeError):
    pass


def payment_configuration() -> dict[str, object]:
    token = os.environ.get("VERTICE_MERCADOPAGO_ACCESS_TOKEN", "").strip()
    if not token:
        return {
            "mode": "demo",
            "configured": False,
            "webhook_configured": False,
        }

    mode = os.environ.get("VERTICE_MERCADOPAGO_MODE", "test").strip().lower()
    if mode not in {"test", "production"}:
        raise IntegrationError("VERTICE_MERCADOPAGO_MODE deve ser 'test' ou 'production'.")
    if mode == "test" and not token.startswith("TEST-"):
        raise IntegrationError(
            "O modo teste exige um access token de teste do Mercado Pago (prefixo TEST-)."
        )
    if mode == "production" and not token.startswith("APP_USR-"):
        raise IntegrationError(
            "O modo produção exige um access token de produção do Mercado Pago (prefixo APP_USR-)."
        )
    if mode == "production" and os.environ.get("VERTICE_ALLOW_LIVE_PAYMENTS") != "yes":
        raise IntegrationError(
            "Pagamentos reais estão bloqueados. Configure VERTICE_ALLOW_LIVE_PAYMENTS=yes apenas após publicar e validar a loja."
        )
    try:
        _public_base_url()
        public_url_configured = True
    except IntegrationError:
        public_url_configured = False
    webhook_configured = bool(
        public_url_configured
        and os.environ.get("VERTICE_MERCADOPAGO_WEBHOOK_SECRET", "").strip()
    )
    return {
        "mode": mode,
        "configured": True,
        "public_url_configured": public_url_configured,
        "webhook_configured": webhook_configured,
        "ready": webhook_configured,
    }


def whatsapp_configuration() -> dict[str, bool]:
    required = (
        "VERTICE_WHATSAPP_ACCESS_TOKEN",
        "VERTICE_WHATSAPP_PHONE_NUMBER_ID",
        "VERTICE_WHATSAPP_CUSTOMER_TEMPLATE",
        "VERTICE_WHATSAPP_SELLER_TEMPLATE",
    )
    return {
        "configured": (
            all(os.environ.get(key, "").strip() for key in required)
            and os.environ.get("VERTICE_WHATSAPP_SEND_ENABLED", "").lower() == "true"
        )
    }


def integration_status() -> dict[str, object]:
    try:
        payments = payment_configuration()
    except IntegrationError as error:
        payments = {"mode": "unavailable", "configured": False, "error": str(error)}
    return {
        "payments": payments,
        "whatsapp": whatsapp_configuration(),
    }


def _request_json(
    url: str,
    payload: dict | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 20,
) -> dict:
    request_headers = {"Accept": "application/json"}
    body = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, data=body, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = response.read()
    except urllib.error.HTTPError as error:
        error.read()
        raise IntegrationError(
            f"O serviço externo recusou a solicitação (HTTP {error.code})."
        ) from None
    except (urllib.error.URLError, TimeoutError) as error:
        raise IntegrationError(
            "Não foi possível conectar ao serviço externo. Verifique a rede e tente novamente."
        ) from error
    try:
        result = json.loads(response_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise IntegrationError("O serviço externo retornou uma resposta inválida.") from error
    if not isinstance(result, dict):
        raise IntegrationError("O serviço externo retornou uma resposta inválida.")
    return result


def _public_base_url() -> str:
    raw_url = os.environ.get("VERTICE_PUBLIC_BASE_URL", "").strip().rstrip("/")
    parsed = urllib.parse.urlsplit(raw_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise IntegrationError(
            "Configure VERTICE_PUBLIC_BASE_URL com a URL HTTPS pública do site/túnel para habilitar o checkout real."
        )
    if parsed.hostname.lower() in {"localhost", "127.0.0.1", "::1"}:
        raise IntegrationError("O checkout real precisa de uma URL pública HTTPS, não localhost.")
    return raw_url


def validate_checkout_setup() -> dict[str, object]:
    config = payment_configuration()
    if not config["configured"]:
        raise IntegrationError("O Mercado Pago não está configurado.")
    _public_base_url()
    if not config["webhook_configured"]:
        raise IntegrationError(
            "Configure VERTICE_MERCADOPAGO_WEBHOOK_SECRET antes de ativar o checkout, para confirmar pagamentos com segurança."
        )
    return config


def create_checkout_preference(
    order_id: str,
    customer_email: str,
    items: list[dict],
    payment_method: str,
) -> dict[str, str]:
    config = payment_configuration()
    if not config["configured"]:
        raise IntegrationError("O Mercado Pago não está configurado.")
    token = os.environ["VERTICE_MERCADOPAGO_ACCESS_TOKEN"].strip()
    base_url = _public_base_url()
    excluded_types = {
        "pix": {"ticket", "credit_card", "debit_card", "prepaid_card"},
        "card": {"bank_transfer", "ticket"},
        "boleto": {"bank_transfer", "credit_card", "debit_card", "prepaid_card"},
    }
    if payment_method not in excluded_types:
        raise IntegrationError("A forma de pagamento selecionada não é suportada.")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    expires_at = (now + timedelta(days=1)).isoformat()
    preference = {
        "items": [
            {
                "id": item["product_id"],
                "title": item["product_name"],
                "quantity": item["quantity"],
                "unit_price": float(Decimal(item["unit_price_cents"]) / Decimal(100)),
                "currency_id": "BRL",
            }
            for item in items
        ],
        "payer": {"email": customer_email},
        "external_reference": order_id,
        "notification_url": f"{base_url}/api/webhooks/mercadopago",
        "back_urls": {
            state: f"{base_url}/pedido/{order_id}"
            for state in ("success", "pending", "failure")
        },
        "auto_return": "approved",
        "payment_methods": {
            "excluded_payment_types": [
                {"id": payment_type}
                for payment_type in sorted(excluded_types[payment_method])
            ]
        },
        "expires": True,
        "expiration_date_from": now.isoformat(),
        "expiration_date_to": expires_at,
    }
    # Checkout Pro is hosted by Mercado Pago: card data never passes through this store.
    result = _request_json(
        "https://api.mercadopago.com/checkout/preferences",
        preference,
        {"Authorization": f"Bearer {token}"},
    )
    checkout_url = result.get(
        "sandbox_init_point" if config["mode"] == "test" else "init_point"
    )
    preference_id = result.get("id")
    if not isinstance(checkout_url, str) or not checkout_url.startswith("https://"):
        raise IntegrationError("O Mercado Pago não retornou um link de checkout seguro.")
    if not isinstance(preference_id, str) or not preference_id:
        raise IntegrationError("O Mercado Pago não retornou o identificador do checkout.")
    return {"id": preference_id, "checkout_url": checkout_url}


def get_payment(payment_id: str) -> dict:
    if not re.fullmatch(r"\d{1,30}", payment_id):
        raise IntegrationError("O identificador do pagamento é inválido.")
    token = os.environ.get("VERTICE_MERCADOPAGO_ACCESS_TOKEN", "").strip()
    if not token:
        raise IntegrationError("O Mercado Pago não está configurado.")
    return _request_json(
        f"https://api.mercadopago.com/v1/payments/{payment_id}",
        headers={"Authorization": f"Bearer {token}"},
    )


def verify_mercadopago_signature(
    payment_id: str,
    request_id: str,
    signature_header: str,
    secret: str,
) -> bool:
    if not re.fullmatch(r"\d{1,30}", payment_id) or not request_id or not secret:
        return False
    parts = {}
    for field in signature_header.split(","):
        key, separator, value = field.strip().partition("=")
        if separator and key in {"ts", "v1"}:
            parts[key] = value
    timestamp = parts.get("ts", "")
    supplied_digest = parts.get("v1", "")
    if not timestamp.isdigit() or not re.fullmatch(r"[a-fA-F0-9]{64}", supplied_digest):
        return False
    manifest = f"id:{payment_id};request-id:{request_id};ts:{timestamp};"
    expected_digest = hmac.new(
        secret.encode("utf-8"), manifest.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(supplied_digest.lower(), expected_digest)


def normalize_whatsapp_number(value: str) -> str:
    number = re.sub(r"\D", "", value)
    if len(number) in {10, 11}:
        return f"55{number}"
    if len(number) in {12, 13} and number.startswith("55"):
        return number
    raise IntegrationError(
        "Informe um telefone brasileiro com DDD ou em formato internacional com DDI."
    )


def send_whatsapp_template(
    phone_number_id: str,
    recipient: str,
    template_name: str,
    parameters: list[str],
) -> str:
    access_token = os.environ.get("VERTICE_WHATSAPP_ACCESS_TOKEN", "").strip()
    api_version = os.environ.get("VERTICE_WHATSAPP_API_VERSION", "v27.0").strip()
    if (
        not access_token
        or not re.fullmatch(r"\d{5,30}", phone_number_id)
        or not re.fullmatch(r"[A-Za-z0-9_]{1,512}", template_name)
        or not re.fullmatch(r"v\d+\.\d+", api_version)
    ):
        raise IntegrationError("A configuração da WhatsApp Cloud API está incompleta.")
    body_parameters = [
        {"type": "text", "text": value[:1024]} for value in parameters
    ]
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": normalize_whatsapp_number(recipient),
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": os.environ.get("VERTICE_WHATSAPP_TEMPLATE_LANGUAGE", "pt_BR")},
            "components": [{"type": "body", "parameters": body_parameters}],
        },
    }
    result = _request_json(
        f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages",
        payload,
        {"Authorization": f"Bearer {access_token}"},
    )
    messages = result.get("messages")
    if not isinstance(messages, list) or not messages or not isinstance(messages[0], dict):
        raise IntegrationError("A WhatsApp Cloud API não confirmou o envio da mensagem.")
    message_id = messages[0].get("id")
    if not isinstance(message_id, str) or not message_id:
        raise IntegrationError("A WhatsApp Cloud API não retornou o identificador da mensagem.")
    return message_id
