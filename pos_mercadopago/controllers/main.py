from odoo import http
from odoo.http import request, Response
import requests
import pprint
import json
import logging
import uuid
from odoo.exceptions import ValidationError
from datetime import datetime, timezone

_logger = logging.getLogger(__name__)

class MercadoPagoController(http.Controller):

    @http.route('/pos/mercadopago/notifications', type='http', auth='public', website=True, csrf=False)
    def notification_webhook(self, **kwargs):
        merchant_order_id = kwargs.get('data.id')
        notification_type = kwargs.get('type')

        if merchant_order_id:
            external_reference = False
            payment = False
            if notification_type == 'payment':
                payment = self.get_payment_endpoint(payment_id=merchant_order_id)

                if payment == False:
                    return Response(
                        json.dumps({ "error": True, "message": "Hubo un error al buscar el pago" }),
                        status=200
                    )

                payment_status = payment.get("status")
                if payment_status != "approved":
                    _logger.info("Notificacion de pago recibida con status '%s', ignorando (payment_id: %s)", payment_status, merchant_order_id)
                    return Response(
                        json.dumps({ "error": False, "message": f"Pago con status '{payment_status}', no se procesa" }),
                        status=200
                    )

                external_reference = payment["external_reference"]
            
            elif notification_type == "merchant_order":
                merchant_order = self.get_merchant_order_mp(merchant_order_id)

                if merchant_order == False:
                    return Response(
                        json.dumps({ "error": True, "message": "Hubo un error al buscar la orden de pago" }),
                        status=200
                    )

                external_reference = merchant_order.get("external_reference")
            else:
                return Response(
                    json.dumps({ "error": True, "message": "Hubo un error al buscar el orden de pago o el pago" }),
                    status=200
                )

            order = request.env["pos.order"].sudo().search([("name","=",external_reference)],limit=1)

            if not order:
                return Response(
                    json.dumps({ "error": True, "message": f"Orden no encontrada en el sistema, numero de referencia: {external_reference}" }),
                    status=404
                )
            
            payment_method = order.session_id.config_id.payment_method_ids.filtered(
                lambda pm: pm.use_payment_terminal == 'mercado_pago'
            )[:1]
            if not payment_method:
                payment_method = request.env["pos.payment.method"].sudo().search([("use_payment_terminal","=","mercado_pago")], limit=1)

            if payment:
                dt = datetime.fromisoformat(payment["date_created"])
                if dt.tzinfo:
                    dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            else:
                dt = None

            order.sudo().write({
                "state":"paid",
                "payment_ids":[(0,0, {
                    "amount": payment.get("transaction_amount", 0) if payment else order.amount_total,
                    "payment_method_id": payment_method.id,
                    "payment_date": dt.strftime('%Y-%m-%d %H:%M:%S') if dt else datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })]
            })

            try:
                mp_provider = request.env['payment.provider'].sudo().search([
                    ('code', '=', 'mercado_pago'),
                    ('company_id', '=', order.company_id.id),
                ], limit=1)
                mp_payment_method = request.env.ref('pos_mercadopago.payment_method_mercado_pago', raise_if_not_found=False)
                mp_payment_id = str(payment.get('id', '')) if payment else ''
                reference = f"MP-{mp_payment_id}" if mp_payment_id else f"MP-{merchant_order_id}"
                amount = payment.get('transaction_amount', 0) if payment else order.amount_total
                partner = order.partner_id or order.company_id.partner_id
                currency = order.currency_id

                tx_vals = {
                    'reference': reference,
                    'provider_id': mp_provider.id if mp_provider else False,
                    'payment_method_id': mp_payment_method.id if mp_payment_method else False,
                    'amount': amount,
                    'currency_id': currency.id,
                    'partner_id': partner.id,
                    'company_id': order.company_id.id,
                    'state': 'done',
                    'provider_reference': mp_payment_id,
                }
                if hasattr(request.env['payment.transaction'], 'pos_order_ids'):
                    tx_vals['pos_order_ids'] = [(4, order.id)]
                # Setear pos_order_id (campo singular de OCA) para que la vista
                # muestre correctamente "Punto de Venta" y demás campos relacionados
                if hasattr(request.env['payment.transaction'], 'pos_order_id'):
                    tx_vals['pos_order_id'] = order.id
                # Linkear también el pos.payment recién creado (para que coincida con el flujo OCA)
                pos_payment = order.payment_ids.filtered(
                    lambda p: p.payment_method_id.id == payment_method.id
                ).sorted('create_date', reverse=True)[:1]
                if pos_payment:
                    if hasattr(request.env['payment.transaction'], 'pos_payment_id'):
                        tx_vals['pos_payment_id'] = pos_payment.id
                    if hasattr(request.env['payment.transaction'], 'transaction_origin'):
                        tx_vals['transaction_origin'] = 'pos_payment'

                with request.env.cr.savepoint():
                    tx = request.env['payment.transaction'].sudo().create(tx_vals)
                # Actualizar payment_transaction_id en el pos.payment si el campo existe
                if pos_payment and hasattr(pos_payment, 'payment_transaction_id'):
                    pos_payment.sudo().payment_transaction_id = tx.id
            except Exception as e:
                _logger.error("Error al crear payment.transaction: %s", str(e))

            return Response(
                json.dumps({ "error": False, "message": f"Pago realizado correctamente, Factura pagada: {external_reference}" }),
                status=200
            ) 
        return Response(json.dumps(
            { "error": True, "message": "No se encontro ni una orden de pago ni un pago" }),
            status=200
        )
        
    def _get_access_token(self, order=None):
        if order:
            till = order.session_id.config_id.mp_tills
            if till and till.store_branch_id.mp_user_id:
                return till.store_branch_id.mp_user_id.access_token
        mp_user = request.env['mercado_pago.user'].sudo().search([], limit=1)
        if mp_user:
            return mp_user.access_token
        return request.env.ref('pos_mercadopago.access_token_mercado_pago_conf').sudo().value

    def get_headers(self, order=None):
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._get_access_token(order)}",
        }

    def get_payment_endpoint(self, payment_id):
        try:
            url = f"https://api.mercadopago.com/v1/payments/{payment_id}"
            headers = self.get_headers()

            result = requests.get(url=url, headers=headers)

            return result.json()
        except Exception as e:
            _logger.info("Hubo un error al buscar el pago")
            return False

    def get_merchant_order_mp(self,merchant_order_id):
        try:
            headers = self.get_headers()

            order_url = f"https://api.mercadopago.com/merchant_orders/{merchant_order_id}"
            response = requests.get(order_url, headers=headers)
            response.raise_for_status()
            order_data = response.json()

            status = order_data.get('status')
            payments = order_data.get('payments', [])

            if status == 'closed' and len(payments) > 0:
                _logger.info(f"La orden {merchant_order_id} está cerrada y con pagos")
                return order_data
            else:
                _logger.info(f"La orden {merchant_order_id} aun no tiene pagos o está abierta.")
                return False
        except requests.exceptions.RequestException as e:
            _logger.error(f"Error procesando orden MercadoPago: {e}")
            return False
        
    @http.route('/pos/get_store_till/', type='json', auth='user', website=True, csrf=False)
    def get_store_till_by_id(self, **kwards):
        param = request.env['ir.config_parameter'].sudo()
        qr_type = param.get_param('pos_mercadopago.mp_qr_type', default='static')
        return {
            "till":request.env["store.tills"].search(
                    [("id","=",kwards["id"])],
                    limit=1
                ).read()[0],
            "qr_type":qr_type
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

    @http.route('/pos/create-order', type='json', auth='user', website=True, csrf=False)
    def create_pos_order(self, **kwards):
        try:

            order_lines = []
            order_mp_lines = []
            amount_tax = 0
            margin = 0
            
            for item in kwards["items"]:
                tax_ids = item.get('tax_ids_after_fiscal_position') or []
                tax = request.env["account.tax"].search([("id", "=", tax_ids[0])], limit=1) if tax_ids else None

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

                margin = margin + (price_subtotal_incl - (item["quantity"] * item["standard_price"]))

                order_lines.append((0,0,{
                    "name":item["title"],
                    "full_product_name":item["title"],
                    "product_id":item["product_id"],
                    "price_unit":item["unit_price"],
                    "qty": item["quantity"],
                    "price_subtotal": price_subtotal,
                    "price_subtotal_incl": price_subtotal_incl,
                    "tax_ids": [(6,0,item["tax_ids"])],
                    "tax_ids_after_fiscal_position": [(6,0,item['tax_ids_after_fiscal_position'])]  
                }))

                if kwards["qr_type"] == 'static':
                    order_mp_lines.append({
                        "id": item["id"],
                        "title": item["title"],
                        "currency_id": "UYU",
                        "unit_price": self.get_price_product(kwards,item,tax) if len(kwards["paymentLines"]) == 1 else (self.get_price_product(kwards,item,tax)/len(kwards["paymentLines"])),
                        "quantity": item["quantity"],
                        "description": item["description"],
                    })
                else:
                    order_mp_lines.append({
                        "id": item["id"],
                        "title": item["title"],
                        "currency_id": "UYU",
                        "unit_price": self.get_price_product(kwards,item,tax),
                        "quantity": item["quantity"],
                        "description": item["description"],
                        "unit_measure": "unit",
                        "total_amount": item["quantity"] * self.get_price_product(kwards,item,tax)
                    })

            session = request.env['pos.session'].sudo().browse(kwards["session_id"])
            order_reference = session.config_id.sequence_id.next_by_id()

            order = request.env["pos.order"].sudo().create({
                "name": order_reference,
                "pos_reference": order_reference,
                "session_id": kwards["session_id"],
                "user_id": kwards["user_id"],
                "partner_id": kwards.get("partner_id") or False,
                "order_salesperson_id": kwards.get("cashier_id") or False,
                "amount_tax": amount_tax,
                "state":"draft",
                "amount_total": self.get_total_amount(order_mp_lines) if len(kwards["paymentLines"]) == 1 else sum(map(lambda p: p["amount"], kwards["paymentLines"])),
                "amount_paid": self.get_total_amount(order_mp_lines) if len(kwards["paymentLines"]) == 1 else sum(map(lambda p: p["amount"], kwards["paymentLines"])),
                "amount_return": self.get_total_amount(order_mp_lines) - kwards["amount_paid"],
                "company_id":kwards["company_id"],
                "lines": order_lines,
            })

            till = request.env["store.tills"].search([("id","=",kwards["store_till_id"])],limit=1)

            if not till:
                return Response(
                    json.dumps({
                        "error": True,
                        "message": "Caja no encontrada"
                    }),
                    status=404
                )

            _logger.info(
                "Creando orden MP — Till: %s (ID: %s) | Sucursal: %s | Usuario MP: %s",
                till.name, till.id,
                till.store_branch_id.name if till.store_branch_id else 'N/A',
                till.store_branch_id.mp_user_id.user_id if till.store_branch_id.mp_user_id else 'N/A',
            )
        
            if kwards["qr_type"] == 'static':
                result = till.create_payment_order(order={
                    "external_reference":order["name"],
                    "items": order_mp_lines
                })
            else:
                result = till.create_payment_order_qr(order={
                    "external_reference":order["name"],
                    "items": order_mp_lines
                })

            _logger.info("Resultado de la orden de pago en mercado pago")
            _logger.info(result)

            return json.dumps({
                "error": False,
                "message": "Orden de pago creada correctamente, por favor escanee el QR",
                "data": result,
                "pos.order": {
                    "id": order.read()[0]["id"]
                }
            })
        except Exception as e:
            _logger.info("Error al crear la orden de pago")
            _logger.info(str(e))
            return json.dumps({
                "error": True,
                "message": "Error al crear la oden de pago"
            })
    
    def get_total_amount(self, items):
        total = 0

        for item in items:
            total = total + (item["unit_price"] * item["quantity"])
        
        return total
    
    @http.route('/pos/delete-order', type='json', auth='user', website=True, csrf=False)
    def delete_pos_order(self, **kwards):
        try:
            order = request.env['pos.order'].sudo().search([("id","=",kwards["order_id"])],limit=1)
            order.state = 'cancel'
            headers = self.get_headers(order=order)
            delete_url = f"https://api.mercadopago.com/instore/qr/seller/collectors/{kwards['user_id']}/pos/{kwards['external_id']}/orders"
            response = requests.delete(delete_url, headers=headers)
            return json.dumps({
                "error": False,
                "message": "Orden de pago eliminada correctamente"
            })

        except Exception as e:
            _logger.info("Error al eliminar la orden de pago")
            _logger.info(str(e))
            return json.dumps({
                "error": True,
                "message": "Error al eliminar la oden de pago"
            })