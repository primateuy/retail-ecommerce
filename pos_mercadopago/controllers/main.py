from odoo import http
from odoo.http import request, Response
import requests
import json
import logging
import hmac
import hashlib

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
            payment = next(
                (p for p in merchant_order.get("payments", []) if p.get("status") == "approved"),
                False
            )

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

        order = pending._create_pos_order_from_mp(payment)
        if not order:
            return Response(
                json.dumps({"error": False, "message": "Orden siendo procesada por otro proceso"}),
                status=200
            )

        return Response(
            json.dumps({"error": False, "message": f"Pago procesado correctamente: {external_reference}"}),
            status=200
        )

    def _mp_get_json(self, url):
        """Consulta la API de MP probando con cada usuario MP configurado.

        El webhook no sabe de qué usuario (sucursal) es el pago hasta leerlo,
        así que se prueba con cada token hasta que uno responda OK.

        Args:
            url (str): URL completa del endpoint de MP.

        Returns:
            dict|bool: JSON de la respuesta, o False si ningún token funcionó.
        """
        pending_model = request.env['mp.pending.order'].sudo()
        # sudo: el webhook es público y los tokens son solo de base.group_system.
        mp_users = request.env['mercado_pago.user'].sudo().search([])
        for mp_user in list(mp_users) or [None]:
            try:
                response = pending_model._mp_request('get', url, mp_user=mp_user)
            except requests.RequestException:
                _logger.exception("Error consultando %s en Mercado Pago", url)
                continue
            if response.status_code < 400:
                return response.json()
            _logger.info(
                "MP devolvio %s para %s con el usuario %s",
                response.status_code, url, mp_user.name if mp_user else 'por defecto'
            )
        return False

    def get_payment_endpoint(self, payment_id):
        return self._mp_get_json(f"https://api.mercadopago.com/v1/payments/{payment_id}")

    def get_merchant_order_mp(self, merchant_order_id):
        order_data = self._mp_get_json(
            f"https://api.mercadopago.com/merchant_orders/{merchant_order_id}"
        )
        if not order_data:
            return False
        if order_data.get('status') == 'closed' and order_data.get('payments'):
            return order_data
        _logger.info("La orden %s aun no tiene pagos o esta abierta.", merchant_order_id)
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
            till = request.env["store.tills"].search(
                [("id", "=", kwards["store_till_id"])], limit=1
            )
            if not till:
                return json.dumps({"error": True, "message": "Caja no encontrada"})

            order_lines = []
            order_mp_lines = []
            amount_tax = 0

            payment_lines_total = sum(p["amount"] for p in kwards["paymentLines"])
            mp_amount = next(
                (p["amount"] for p in kwards["paymentLines"] if p["is_mercado_pago"]),
                payment_lines_total
            )
            # Con varios medios de pago MP cobra solo su parte: se manda un único ítem por
            # ese monto exacto, así lo cobrado coincide siempre con la línea de MP.
            is_partial_mp = len(kwards["paymentLines"]) > 1

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
                    "discount": item.get("discount") or 0,
                    "price_subtotal": price_subtotal,
                    "price_subtotal_incl": price_subtotal_incl,
                    "tax_ids": [[6, 0, item["tax_ids"]]],
                    "tax_ids_after_fiscal_position": [[6, 0, item['tax_ids_after_fiscal_position']]],
                })

                if kwards["qr_type"] == 'static':
                    if is_partial_mp:
                        continue
                    order_mp_lines.append({
                        "id": item["id"],
                        "title": item["title"],
                        "currency_id": currency_name,
                        "unit_price": round(price_subtotal_incl, 2),
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

            if kwards["qr_type"] == 'static' and is_partial_mp:
                order_mp_lines = [{
                    "id": order_reference,
                    "title": f"Pago parcial orden {order_reference}",
                    "currency_id": currency_name,
                    "unit_price": round(mp_amount, 2),
                    "quantity": 1,
                    "description": f"Pago con Mercado Pago de la orden {order_reference}",
                }]

            # El POS manda el total real de la orden; el cálculo viejo queda para clientes con JS cacheado.
            amount_total = kwards.get("amount_total") or (
                self.get_total_amount(order_mp_lines)
                if len(kwards["paymentLines"]) == 1
                else payment_lines_total
            )

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

            request.env['mp.pending.order'].sudo().create({
                'name': order_reference,
                'session_id': session.id,
                'till_id': till.id,
                'order_data': json.dumps({
                    "user_id": kwards["user_id"],
                    "employee_id": kwards.get("employee_id") or False,
                    "partner_id": kwards.get("partner_id") or False,
                    "cashier_id": kwards.get("cashier_id") or False,
                    "company_id": kwards["company_id"],
                    "amount_tax": amount_tax,
                    "amount_total": amount_total,
                    "amount_return": kwards.get("amount_return") or 0,
                    "lines": order_lines,
                    "payment_lines": kwards["paymentLines"],
                }),
            })

            return json.dumps({
                "error": False,
                "message": "QR generado correctamente, por favor escanee el QR",
                "data": result,
                "order_reference": order_reference,
            })

        except Exception:
            _logger.exception("Error al crear la orden de pago")
            return json.dumps({"error": True, "message": "Error al crear la orden de pago"})

    @http.route('/pos/check-mp-order-status', type='json', auth='user', csrf=False)
    def check_mp_order_status(self, **kwargs):
        """Devuelve el estado de una orden MP y, si ya está paga, la registra.

        Si MP tiene un pago aprobado pero el webhook no creó el pos.order, lo
        crea en este momento.

        Returns:
            str: JSON con 'status' ('paid', 'processing', 'pending', 'expired',
                'error' o 'not_found') y, opcionalmente, 'message'.
        """
        order_reference = kwargs.get('order_reference')
        if not order_reference:
            return json.dumps({'status': 'not_found'})

        # sudo: el cajero no tiene acceso de lectura a las órdenes pendientes ni a los pedidos de otros.
        pending = request.env['mp.pending.order'].sudo().search(
            [('name', '=', order_reference)], limit=1
        )
        if not pending:
            existing_order = request.env['pos.order'].sudo().search(
                [('name', '=', order_reference)], limit=1
            )
            if existing_order:
                return json.dumps(self._paid_response(existing_order))
            return json.dumps({'status': 'not_found'})

        status, order = pending._reconcile_with_mp()
        if status == 'paid':
            return json.dumps(self._paid_response(order))
        return json.dumps({'status': status})

    def _paid_response(self, order):
        """Arma la respuesta de pedido pago, avisando si quedó en borrador."""
        response = {'status': 'paid'}
        if order.state == 'draft':
            response['message'] = (
                "El pago fue recibido pero el pedido quedo en borrador para revision."
            )
        return response

    @http.route('/pos/delete-order', type='json', auth='user', csrf=False)
    def delete_pos_order(self, **kwards):
        """Cancela la orden MP pendiente para liberar la caja.

        Nunca cancela si MP tiene un pago aprobado: en ese caso registra el
        pedido y responde 'paid'. Si no se puede consultar MP, no cancela.

        Returns:
            str: JSON con 'error', 'status' y 'message'.
        """
        try:
            order_reference = kwards.get("order_reference")
            # sudo: el cajero no tiene acceso de lectura a las órdenes pendientes ni a los pedidos de otros.
            pending = request.env['mp.pending.order'].sudo().search(
                [("name", "=", order_reference)], limit=1
            )
            if not pending:
                existing_order = request.env['pos.order'].sudo().search(
                    [('name', '=', order_reference)], limit=1
                )
                if existing_order:
                    return json.dumps(dict(self._paid_response(existing_order), error=True))
                return json.dumps({
                    "error": False,
                    "status": "not_found",
                    "message": "La orden no existia en Odoo, se libero la caja"
                })

            status, order = pending._reconcile_with_mp()
            if status == 'paid':
                return json.dumps(dict(self._paid_response(order), error=True))
            if status == 'processing':
                return json.dumps({
                    "error": True,
                    "status": status,
                    "message": "El pago fue recibido y aun se esta procesando, use Comprobar pago"
                })
            if status == 'error':
                return json.dumps({
                    "error": True,
                    "status": status,
                    "message": "No se pudo consultar Mercado Pago, intente de nuevo"
                })

            if status == 'pending' and not pending._cancel_mp_order(
                collector_id=kwards.get('user_id'), external_pos_id=kwards.get('external_id')
            ):
                return json.dumps({
                    "error": True,
                    "status": status,
                    "message": "No se pudo eliminar la orden en Mercado Pago"
                })

            # El cliente pudo haber pagado justo antes de la baja: se verifica una vez más.
            status, order = pending._reconcile_with_mp()
            if status == 'paid':
                return json.dumps(dict(self._paid_response(order), error=True))
            if status in ('processing', 'error'):
                return json.dumps({
                    "error": True,
                    "status": status,
                    "message": "No se pudo confirmar que la orden no fue pagada, use Comprobar pago"
                })

            pending.unlink()
            return json.dumps({"error": False, "status": status, "message": "Orden eliminada correctamente"})

        except Exception:
            _logger.exception("Error al eliminar la orden de pago")
            return json.dumps({"error": True, "message": "Error al eliminar la orden de pago"})
