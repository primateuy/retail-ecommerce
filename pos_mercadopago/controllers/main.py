from odoo import http
from odoo.http import request, Response
import requests
import pprint
import json
import logging
import uuid
from odoo.exceptions import ValidationError
from datetime import datetime

_logger = logging.getLogger(__name__)

class MercadoPagoController(http.Controller):

    @http.route('/pos/mercadopago/notifications', type='http', auth='public', website=True, csrf=False)
    def notification_webhook(self, **kwargs):
        merchant_order_id = kwargs.get('data.id')
        notification_type = kwargs.get('type')

        if merchant_order_id:
            # Referencia de la orden de compra
            external_reference = False
            payment = False
            # Si el tipo de notificacion es de un pago
            if notification_type == 'payment':
                # Obtenemos informacion del pago
                payment = self.get_payment_endpoint(payment_id=merchant_order_id)

                if payment == False:
                    return Response(
                        json.dumps({ "error": True, "message": "Hubo un error al buscar el pago" }),
                        status=200
                    )

                # Verificamos que el pago este aprobado
                payment_status = payment.get("status")
                if payment_status != "approved":
                    _logger.info("Notificacion de pago recibida con status '%s', ignorando (payment_id: %s)", payment_status, merchant_order_id)
                    return Response(
                        json.dumps({ "error": False, "message": f"Pago con status '{payment_status}', no se procesa" }),
                        status=200
                    )

                # Asignamos la referencia externa de la orden
                external_reference = payment["external_reference"]
            
            elif notification_type == "merchant_order":
                # Buscamos la orden de pago
                merchant_order = self.get_merchant_order_mp(merchant_order_id)

                # Validamos si la orden esta abierta, si es asi, retornamos el error
                if merchant_order == False:
                    return Response(
                        json.dumps({ "error": True, "message": "Hubo un error al buscar la orden de pago" }),
                        status=200
                    )

                # Asignamos la referencia externa
                external_reference = merchant_order_id
            else:
                return Response(
                    json.dumps({ "error": True, "message": "Hubo un error al buscar el orden de pago o el pago" }),
                    status=200
                )

            # Registrar el pago y marcar la orden como pagada
            order = request.env["pos.order"].sudo().search([("name","=",external_reference)],limit=1)

            # Validamos si la orden no existe
            if not order:
                return Response(
                    json.dumps({ "error": True, "message": f"Orden no encontrada en el sistema, numero de referencia: {external_reference}" }),
                    status=404
                )
            
            # Buscamos el metodo de pago
            payment_method = request.env["pos.payment.method"].sudo().search([("use_payment_terminal","=","mercado_pago")], limit=1)

            # Formateamos la fecha de la creacion del pago
            dt = datetime.fromisoformat(payment["date_created"])

            # Actualizamos la orden de pago y agregamos un pago a dicha orden
            order.sudo().write({
                "state":"paid",
                # "payment_ids":[(0,0, {
                #     "amount": payment["transaction_amount"],
                #     "payment_method_id": payment_method["id"],
                #     "payment_date": dt.strftime('%Y-%m-%d %H:%M:%S')
                # })]
            })

            # Creamos la transaccion de pago de Mercado Pago
            try:
                mp_provider = request.env['payment.provider'].sudo().search([('code', '=', 'mercado_pago')], limit=1)
                mp_payment_method = request.env.ref('pos_mercadopago.payment_method_mercado_pago', raise_if_not_found=False)
                request.env['mp.payment.transaction'].sudo().create({
                    'name': payment.get('external_reference', external_reference),
                    'payment_method_id': mp_payment_method.id if mp_payment_method else False,
                    'provider_id': mp_provider.id if mp_provider else False,
                    'company_id': order.company_id.id,
                    'amount': payment.get('transaction_amount', 0),
                    'pos_order_id': order.id,
                })
            except Exception as e:
                _logger.error("Error al crear mp.payment.transaction: %s", str(e))

            # Retornamos que todo bien
            return Response(
                json.dumps({ "error": False, "message": f"Pago realizado correctamente, Factura pagada: {external_reference}" }),
                status=200
            ) 
            # self.process_mercadopago_payment(merchant_order_id)
        return Response(json.dumps(
            { "error": True, "message": "No se encontro ni una orden de pago ni un pago" }),
            status=200
        )
        
    def _get_access_token(self, order=None):
        if order:
            till = order.session_id.config_id.mp_tills
            if till and till.store_branch_id.application_id:
                return till.store_branch_id.application_id.access_token
        # Fallback: buscar la primera app disponible
        app = request.env['mercado_pago.applications'].sudo().search([], limit=1)
        if app:
            return app.access_token
        # Ultimo fallback: config global
        return request.env.ref('pos_mercadopago.access_token_mercado_pago_conf').sudo().value

    def get_headers(self, order=None):
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._get_access_token(order)}",
        }

    # Metodo para verificar el pago de una factura
    def get_payment_endpoint(self, payment_id):
        try:
            # Preparamos endpoint y headers
            url = f"https://api.mercadopago.com/v1/payments/{payment_id}"
            headers = self.get_headers()

            # Realizamos peticion
            result = requests.get(url=url, headers=headers)

            # Retornamos el resultado
            return result.json()
        except Exception as e:
            _logger.info("Hubo un error al buscar el pago")
            return False

    # Metodo para obtener la orden de pago desde mercado pago
    def get_merchant_order_mp(self,merchant_order_id):
        try:
            # Obtenemos los headers
            headers = self.get_headers()

            # 1. Consultar los detalles de la orden
            order_url = f"https://api.mercadopago.com/merchant_orders/{merchant_order_id}"
            response = requests.get(order_url, headers=headers)
            response.raise_for_status()
            order_data = response.json()

            status = order_data.get('status')
            payments = order_data.get('payments', [])

            # 2. Verificar si la orden está cerrada y con pagos
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
    
    # Metodo para obtener el precio del producto
    def get_price_product(self, kwards, product, tax):
        # Retornamos el monto con impuestos
        if len(kwards["paymentLines"]) == 1:
            return round(product["unit_price"] + ((tax["amount"]/100) * product["unit_price"]), 2)
        
        # Retornamos el precio seleccionado
        for payment in kwards["paymentLines"]:
            if payment["is_mercado_pago"]:
                return payment["amount"]

    @http.route('/pos/create-order', type='json', auth='user', website=True, csrf=False)
    def create_pos_order(self, **kwards):
        try:

            order_lines = []
            order_mp_lines = []
            payment_ids = []
            amount_tax = 0
            margin = 0
            
            for item in kwards["items"]:
                tax = request.env["account.tax"].search([("id","=",item['tax_ids_after_fiscal_position'][0])], limit=1)
                
                # Calculamos el precio con impuestos incluidos
                price_subtotal_incl = item["unit_price"] + ((tax["amount"]/100) * item["unit_price"])

                # Sumamos los impuestos
                amount_tax = amount_tax + ((tax["amount"]/100) * item["unit_price"])

                # Sumamos los margenes de ganancia
                margin = margin + (price_subtotal_incl - (item["quantity"] * item["standard_price"]))

                # Lista de ordenes
                order_lines.append((0,0,{
                    "name":item["title"],
                    "full_product_name":item["title"],
                    "product_id":item["product_id"],
                    "price_unit":item["unit_price"],
                    "qty": item["quantity"],
                    "price_subtotal": item["unit_price"],
                    "price_subtotal_incl": price_subtotal_incl,
                    "tax_ids": [(6,0,item["tax_ids"])],
                    "tax_ids_after_fiscal_position": [(6,0,item['tax_ids_after_fiscal_position'])]  
                }))

                # Lista de items para mercado pago
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

            # Organizamos los pagos para registrarlos tambien
            for payment in kwards["paymentLines"]:
                payment_ids.append((0,0,{
                    "amount":payment["amount"],
                    "name": payment["name"],
                    "payment_method_id": payment["payment_method_id"],
                }))

            # Generamos la referencia de la orden una sola vez
            order_reference = request.env['ir.sequence'].sudo().next_by_code('pos.order.line')
            
            # Creamos la orden en odoo
            order = request.env["pos.order"].create({
                "name": order_reference,
                "pos_reference": order_reference,
                "session_id": kwards["session_id"],
                "user_id": kwards["user_id"],
                "amount_tax": amount_tax,
                "state":"draft",
                # "amount_total": self.get_total_amount(order_mp_lines) if len(kwards["paymentLines"]) == 1 else self.get_total_amount_by_order_lines(order_lines),
                "amount_total": self.get_total_amount(order_mp_lines) if len(kwards["paymentLines"]) == 1 else sum(map(lambda p: p["amount"], kwards["paymentLines"])),
                # "amount_paid": kwards["amount_paid"],
                "amount_paid": self.get_total_amount(order_mp_lines) if len(kwards["paymentLines"]) == 1 else sum(map(lambda p: p["amount"], kwards["paymentLines"])),
                "amount_return": self.get_total_amount(order_mp_lines) - kwards["amount_paid"],
                # "amount_return": 0,
                "company_id":kwards["company_id"],
                "lines": order_lines,
                "payment_ids": payment_ids
            })

            # Buscamos la caja
            till = request.env["store.tills"].search([("id","=",kwards["store_till_id"])],limit=1)

            # Validamos
            if not till:
                return Response(
                    json.dumps({
                        "error": True,
                        "message": "Caja no encontrada"
                    }),
                    status=404
                )
        
            if kwards["qr_type"] == 'static':
                # Creamos la orden de pago en mercado pago
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
            # Obtenemos los headers
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