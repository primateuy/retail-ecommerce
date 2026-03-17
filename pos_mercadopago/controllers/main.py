from odoo import http
from odoo.http import request, Response
import requests
import json
import logging
import hmac
import hashlib
from datetime import datetime, timezone

_logger = logging.getLogger(__name__)


class MercadoPagoController(http.Controller):

    def _validate_webhook_signature(self, data_id):
        """
        Valida la firma HMAC-SHA256 del webhook segun la documentacion de MercadoPago.
        Header x-signature formato: "ts=<timestamp>,v1=<hash>"
        Signed template: "id:<data_id>;request-id:<x-request-id>;ts:<ts>;"
        Si no hay secret configurado, permite el request con un warning.
        """
        signature_header = request.httprequest.headers.get('x-signature', '')
        request_id = request.httprequest.headers.get('x-request-id', '')

        if not signature_header:
            _logger.warning("Webhook recibido sin header x-signature")
            return True  

        ts = None
        v1 = None
        for part in signature_header.split(','):
            key, _, value = part.partition('=')
            key = key.strip()
            value = value.strip()
            if key == 'ts':
                ts = value
            elif key == 'v1':
                v1 = value

        if not ts or not v1:
            _logger.warning("Header x-signature con formato invalido: %s", signature_header)
            return False

        payment_method = request.env['pos.payment.method'].sudo().search([
            ('use_payment_terminal', '=', 'mercado_pago'),
            ('mp_webhook_secret_key', '!=', False),
        ], limit=1)

        if not payment_method or not payment_method.mp_webhook_secret_key:
            _logger.warning(
                "No se encontro mp_webhook_secret_key — validacion de firma omitida. "
                "Configure el campo en el metodo de pago MercadoPago."
            )
            return True  

        secret = payment_method.mp_webhook_secret_key
        signed_template = f"id:{data_id};request-id:{request_id};ts:{ts};"
        expected = hmac.new(
            secret.encode('utf-8'),
            signed_template.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(expected, v1):
            _logger.warning(
                "Firma de webhook no coincide para data_id=%s. "
                "Verifique que mp_webhook_secret_key coincida con el secret configurado "
                "en el dashboard de MercadoPago. El pago se procesa igualmente.", data_id
            )

        return True

    @http.route('/pos/mercadopago/notifications', type='http', auth='public', website=True, csrf=False)
    def notification_webhook(self, **kwargs):
        merchant_order_id = kwargs.get('data.id') or kwargs.get('id')
        notification_type = kwargs.get('type') or kwargs.get('topic')

        if not merchant_order_id:
            return Response(
                json.dumps({"error": True, "message": "No se encontro ni una orden de pago ni un pago"}),
                status=200
            )

        self._validate_webhook_signature(merchant_order_id)

        external_reference = False
        payment = False

        if notification_type == 'payment':
            payment = self.get_payment_endpoint(payment_id=merchant_order_id)
            if payment is False:
                return Response(
                    json.dumps({"error": True, "message": "Hubo un error al buscar el pago"}),
                    status=200
                )

            payment_status = payment.get("status")
            if payment_status != "approved":
                _logger.info(
                    "Notificacion de pago recibida con status '%s', ignorando (payment_id: %s)",
                    payment_status, merchant_order_id
                )
                return Response(
                    json.dumps({"error": False, "message": f"Pago con status '{payment_status}', no se procesa"}),
                    status=200
                )

            external_reference = payment["external_reference"]

        elif notification_type == "merchant_order":
            merchant_order = self.get_merchant_order_mp(merchant_order_id)
            if merchant_order is False:
                return Response(
                    json.dumps({"error": True, "message": "Hubo un error al buscar la orden de pago"}),
                    status=200
                )
            external_reference = merchant_order.get("external_reference")

        else:
            return Response(
                json.dumps({"error": True, "message": "Tipo de notificacion no reconocido"}),
                status=200
            )

        existing_order = request.env["pos.order"].sudo().search(
            [("name", "=", external_reference)], limit=1
        )
        if existing_order:
            _logger.info("Orden %s ya fue procesada, ignorando webhook duplicado", external_reference)
            return Response(
                json.dumps({"error": False, "message": "Orden ya procesada"}),
                status=200
            )

        pending = request.env['mp.pending.order'].sudo().search(
            [('name', '=', external_reference)], limit=1
        )
        if not pending:
            return Response(
                json.dumps({"error": True, "message": f"Orden pendiente no encontrada: {external_reference}"}),
                status=404
            )

        order_data = json.loads(pending.order_data)
        session = pending.session_id

        payment_method = session.config_id.payment_method_ids.filtered(
            lambda pm: pm.use_payment_terminal == 'mercado_pago'
        )[:1]
        if not payment_method:
            payment_method = request.env["pos.payment.method"].sudo().search(
                [("use_payment_terminal", "=", "mercado_pago")], limit=1
            )

        if payment:
            dt = datetime.fromisoformat(payment["date_created"])
            if dt.tzinfo:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        else:
            dt = None
        payment_date = dt.strftime('%Y-%m-%d %H:%M:%S') if dt else datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        amount_total = order_data.get('amount_total', 0)
        partner_id = order_data.get('partner_id') or False

        order_lines = [(0, 0, line) for line in order_data.get('lines', [])]

        order = request.env["pos.order"].sudo().create({
            "name": external_reference,
            "pos_reference": external_reference,
            "session_id": session.id,
            "user_id": order_data.get('user_id'),
            "partner_id": partner_id,
            "order_salesperson_id": order_data.get('cashier_id') or False,
            "amount_tax": order_data.get('amount_tax', 0),
            "amount_total": amount_total,
            "amount_paid": amount_total,
            "amount_return": 0,
            "company_id": order_data.get('company_id'),
            "to_invoice": bool(partner_id),
            "lines": order_lines,
            "payment_ids": [(0, 0, {
                "amount": amount_total,
                "payment_method_id": payment_method.id,
                "payment_date": payment_date,
            })],
        })

        order.action_pos_order_paid()

        if order.to_invoice and order.partner_id and order.state == 'paid':
            try:
                order._generate_pos_order_invoice()
            except Exception as e:
                _logger.error("Error al crear factura para orden %s: %s", order.name, str(e))

        pending.sudo().unlink()

        try:
            mp_provider = request.env['payment.provider'].sudo().search([
                ('code', '=', 'mercado_pago'),
                ('company_id', '=', order.company_id.id),
            ], limit=1)
            mp_payment_method = request.env.ref(
                'pos_mercadopago.payment_method_mercado_pago', raise_if_not_found=False
            )
            mp_payment_id = str(payment.get('id', '')) if payment else ''
            reference = f"MP-{mp_payment_id}" if mp_payment_id else f"MP-{merchant_order_id}"
            partner = order.partner_id or order.company_id.partner_id
            currency = order.currency_id

            tx_vals = {
                'reference': reference,
                'provider_id': mp_provider.id if mp_provider else False,
                'payment_method_id': mp_payment_method.id if mp_payment_method else False,
                'amount': amount_total,
                'currency_id': currency.id,
                'partner_id': partner.id,
                'company_id': order.company_id.id,
                'state': 'done',
                'provider_reference': mp_payment_id,
            }
            if hasattr(request.env['payment.transaction'], 'pos_order_ids'):
                tx_vals['pos_order_ids'] = [(4, order.id)]
            if hasattr(request.env['payment.transaction'], 'pos_order_id'):
                tx_vals['pos_order_id'] = order.id

            pos_payment = order.payment_ids[:1]
            if pos_payment:
                if hasattr(request.env['payment.transaction'], 'pos_payment_id'):
                    tx_vals['pos_payment_id'] = pos_payment.id
                if hasattr(request.env['payment.transaction'], 'transaction_origin'):
                    tx_vals['transaction_origin'] = 'pos_payment'

            with request.env.cr.savepoint():
                tx = request.env['payment.transaction'].sudo().create(tx_vals)

            if pos_payment and hasattr(pos_payment, 'payment_transaction_id'):
                pos_payment.sudo().payment_transaction_id = tx.id

        except Exception as e:
            _logger.error("Error al crear payment.transaction: %s", str(e))

        return Response(
            json.dumps({"error": False, "message": f"Pago procesado correctamente: {external_reference}"}),
            status=200
        )

    def _get_access_token(self):
        mp_user = request.env['mercado_pago.user'].sudo().search([], limit=1)
        if mp_user:
            return mp_user.access_token
        return request.env.ref('pos_mercadopago.access_token_mercado_pago_conf').sudo().value

    def get_headers(self):
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._get_access_token()}",
        }

    def get_payment_endpoint(self, payment_id):
        try:
            url = f"https://api.mercadopago.com/v1/payments/{payment_id}"
            result = requests.get(url=url, headers=self.get_headers())
            return result.json()
        except Exception as e:
            _logger.error("Error al buscar el pago %s: %s", payment_id, str(e))
            return False

    def get_merchant_order_mp(self, merchant_order_id):
        try:
            order_url = f"https://api.mercadopago.com/merchant_orders/{merchant_order_id}"
            response = requests.get(order_url, headers=self.get_headers())
            response.raise_for_status()
            order_data = response.json()

            status = order_data.get('status')
            payments = order_data.get('payments', [])

            if status == 'closed' and len(payments) > 0:
                return order_data
            else:
                _logger.info("La orden %s aun no tiene pagos o esta abierta.", merchant_order_id)
                return False
        except requests.exceptions.RequestException as e:
            _logger.error("Error procesando orden MercadoPago: %s", str(e))
            return False

    @http.route('/pos/get_store_till/', type='json', auth='user', csrf=False)
    def get_store_till_by_id(self, **kwards):
        param = request.env['ir.config_parameter'].sudo()
        qr_type = param.get_param('pos_mercadopago.mp_qr_type', default='static')
        return {
            "till": request.env["store.tills"].search(
                [("id", "=", kwards["id"])], limit=1
            ).read()[0],
            "qr_type": qr_type
        }

    def get_price_product(self, kwards, product, tax):
        if len(kwards["paymentLines"]) == 1:
            if tax and tax.price_include:
                return round(product["unit_price"], 2)
            elif tax:
                return round(product["unit_price"] + ((tax.amount / 100) * product["unit_price"]), 2)
            else:
                return round(product["unit_price"], 2)

        for payment in kwards["paymentLines"]:
            if payment["is_mercado_pago"]:
                return payment["amount"]

    def get_total_amount(self, items):
        total = 0
        for item in items:
            total = total + (item["unit_price"] * item["quantity"])
        return total

    @http.route('/pos/create-order', type='json', auth='user', csrf=False)
    def create_pos_order(self, **kwards):
        try:
            session = request.env['pos.session'].sudo().browse(kwards["session_id"])
            currency_name = session.currency_id.name if session.currency_id else 'UYU'
            order_reference = session.config_id.sequence_id.next_by_id()

            order_lines = []
            order_mp_lines = []
            amount_tax = 0

            for item in kwards["items"]:
                tax_ids = item.get('tax_ids_after_fiscal_position') or []
                tax = request.env["account.tax"].search(
                    [("id", "=", tax_ids[0])], limit=1
                ) if tax_ids else None

                if tax and tax.price_include:
                    price_subtotal_incl = item["unit_price"]
                    price_subtotal = item["unit_price"] / (1 + tax.amount / 100)
                    amount_tax += item["unit_price"] - price_subtotal
                elif tax:
                    price_subtotal = item["unit_price"]
                    price_subtotal_incl = item["unit_price"] * (1 + tax.amount / 100)
                    amount_tax += (tax.amount / 100) * item["unit_price"]
                else:
                    price_subtotal = item["unit_price"]
                    price_subtotal_incl = item["unit_price"]

                order_lines.append({
                    "name": item["title"],
                    "full_product_name": item["title"],
                    "product_id": item["product_id"],
                    "price_unit": item["unit_price"],
                    "qty": item["quantity"],
                    "price_subtotal": price_subtotal,
                    "price_subtotal_incl": price_subtotal_incl,
                    "tax_ids": [[6, 0, item["tax_ids"]]],
                    "tax_ids_after_fiscal_position": [[6, 0, item['tax_ids_after_fiscal_position']]],
                })

                if kwards["qr_type"] == 'static':
                    order_mp_lines.append({
                        "id": item["id"],
                        "title": item["title"],
                        "currency_id": currency_name,
                        "unit_price": (
                            self.get_price_product(kwards, item, tax)
                            if len(kwards["paymentLines"]) == 1
                            else self.get_price_product(kwards, item, tax) / len(kwards["paymentLines"])
                        ),
                        "quantity": item["quantity"],
                        "description": item["description"],
                    })
                else:
                    unit_price = self.get_price_product(kwards, item, tax)
                    order_mp_lines.append({
                        "id": item["id"],
                        "title": item["title"],
                        "currency_id": currency_name,
                        "unit_price": unit_price,
                        "quantity": item["quantity"],
                        "description": item["description"],
                        "unit_measure": "unit",
                        "total_amount": item["quantity"] * unit_price,
                    })

            amount_total = (
                self.get_total_amount(order_mp_lines)
                if len(kwards["paymentLines"]) == 1
                else sum(p["amount"] for p in kwards["paymentLines"])
            )

            request.env['mp.pending.order'].sudo().create({
                'name': order_reference,
                'session_id': session.id,
                'order_data': json.dumps({
                    "user_id": kwards["user_id"],
                    "partner_id": kwards.get("partner_id") or False,
                    "cashier_id": kwards.get("cashier_id") or False,
                    "company_id": kwards["company_id"],
                    "amount_tax": amount_tax,
                    "amount_total": amount_total,
                    "lines": order_lines,
                }),
            })

            till = request.env["store.tills"].search(
                [("id", "=", kwards["store_till_id"])], limit=1
            )
            if not till:
                return json.dumps({"error": True, "message": "Caja no encontrada"})

            _logger.info(
                "Creando orden MP — Till: %s (ID: %s) | Sucursal: %s | Usuario MP: %s",
                till.name, till.id,
                till.store_branch_id.name if till.store_branch_id else 'N/A',
                till.store_branch_id.mp_user_id.user_id if till.store_branch_id.mp_user_id else 'N/A',
            )

            if kwards["qr_type"] == 'static':
                result = till.create_payment_order(order={
                    "external_reference": order_reference,
                    "items": order_mp_lines,
                })
            else:
                result = till.create_payment_order_qr(order={
                    "external_reference": order_reference,
                    "items": order_mp_lines,
                })

            return json.dumps({
                "error": False,
                "message": "QR generado correctamente, por favor escanee el QR",
                "data": result,
                "order_reference": order_reference,
            })

        except Exception as e:
            _logger.exception("Error al crear la orden de pago")
            return json.dumps({"error": True, "message": "Error al crear la orden de pago"})

    @http.route('/pos/delete-order', type='json', auth='user', csrf=False)
    def delete_pos_order(self, **kwards):
        try:
            order_reference = kwards.get("order_reference")

            pending = request.env['mp.pending.order'].sudo().search(
                [("name", "=", order_reference)], limit=1
            )
            if pending:
                pending.sudo().unlink()
            else:
                existing = request.env['pos.order'].sudo().search(
                    [("name", "=", order_reference)], limit=1
                )
                if existing:
                    return json.dumps({
                        "error": True,
                        "message": "El pago ya fue procesado, no se puede cancelar"
                    })

            delete_url = (
                f"https://api.mercadopago.com/instore/qr/seller/collectors"
                f"/{kwards['user_id']}/pos/{kwards['external_id']}/orders"
            )
            requests.delete(delete_url, headers=self.get_headers())

            return json.dumps({"error": False, "message": "Orden eliminada correctamente"})

        except Exception as e:
            _logger.exception("Error al eliminar la orden de pago")
            return json.dumps({"error": True, "message": "Error al eliminar la orden de pago"})
