from odoo import _, api, fields, models, tools
from odoo.exceptions import ValidationError
import requests
import qrcode
from io import BytesIO
import base64
from datetime import datetime, timedelta

import logging

_logger = logging.getLogger(__name__)

class StoreTills(models.Model):

    _name = 'store.tills'
    _description = 'Store tills of a store branch'

    # active = fields.Boolean(default=True)
    name = fields.Char(required=True)
    store_branch_id = fields.Many2one(
        'store.branches',
        string='Store Branch',
        required=True
    )
    fixed_amount = fields.Boolean(default=True)
    external_id = fields.Char(required=False)
    category = fields.Selection([
            ('service', 'Service Station'),
            ('gastronomy','Gastronomy')
        ], 
        required=True, 
        default="service"
    )

    # MercadoPago Data
    pos_id_mp = fields.Char()
    qr_url = fields.Char()
    qr_template_document = fields.Char()
    qr_template_image = fields.Char()
    qr_code = fields.Char()
    uuid_mp = fields.Char()
    user_id_mp = fields.Char()
    status_mp = fields.Char()

    @api.model
    def create(self, values):
        result = super().create(values)
        if not self.env.context.get('skip_mp_create'):
            if not values.get('external_id'):
                result.write({
                    "external_id": result.generate_external_id()
                })
            result.create_pos_mercado_pago()
        return result
    
    # Methods
    # Method to create POS in MercadoPago
    def create_pos_mercado_pago(self):
        try:
            # Prepare request
            headers = self.get_endpoint_headers()
            body = self.get_pos()
            url = self.get_endpoint_url()

            # Enviamos la solicitud POST
            mp_user = self.store_branch_id.mp_user_id
            if mp_user:
                response = mp_user._make_request('post', url, json=body)
            else:
                response = requests.post(url, json=body, headers=headers)

            # Validamos si hubo un error al crear la sucursal
            if response.status_code >= 400:
                raise ValidationError(_("An error occurred while creating the pos"))
            
            data = response.json()

            self.write({
                "pos_id_mp": data["id"],
                "qr_url": data["qr"]["image"],
                "qr_template_document": data["qr"]["template_document"],
                "qr_template_image": data["qr"]["template_image"],
                "qr_code": data["qr_code"],
                "uuid_mp": data["uuid"],
                "user_id_mp": data["user_id"],
                "status_mp": data["status"]
            })
        except Exception as e:
            _logger.info("Hubo un error al crear el punto de venta en Mercado Pago")
            _logger.info(str(e))
            raise ValidationError(_("An error occurred while creating the pos"))

    # Generate external id to POS
    def generate_external_id(self):
        return f"{self.store_branch_id.external_id}POS{self.id}"

    # Get url endpoint
    def get_endpoint_url(self):
        return "https://api.mercadopago.com/pos"

    def get_endpoint_headers(self):
        mp_user = self.store_branch_id.mp_user_id
        if mp_user:
            token = mp_user.access_token
        else:
            token = self.env.ref('pos_mercadopago.access_token_mercado_pago_conf').sudo().value
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }

    # Get data point of sale
    def get_pos(self):
        return {
            "name": self.name,
            "fixed_amount": self.fixed_amount,
            "store_id": self.store_branch_id.mp_store_branch_id,
            "external_store_id": self.store_branch_id.external_id,
            "external_id": self.external_id,
            "category": int(self.get_category_code())
        }

    # Get code category
    def get_category_code(self):
        return self.env.ref(f"pos_mercadopago.{self.category}_category_code_conf").sudo().value

    # Create a payment order
    def create_payment_order(self, order):
        return self.process_create_order(order=order)
    
    def create_payment_order_qr(self, order):
        return self.process_create_payment_order_qr_tramma(order=order)
    
    # Create an order in this pos
    def process_create_order(self, order):
        try:
            url = self.get_create_order_mp_endpoint()
            headers = self.get_headers_create_order_mp()
            body = self.get_body_create_order_mp(order)

            # Enviamos la solicitud POST
            mp_user = self.store_branch_id.mp_user_id
            if mp_user:
                response = mp_user._make_request('post', url, json=body)
            else:
                response = requests.post(url, json=body, headers=headers)

            # Validamos si hubo un error al crear la sucursal
            if response.status_code >= 400:
                raise ValidationError(_("An error occurred while creating the payment order"))
            
            data = response.json()

            return data
        except Exception as e:
            
            _logger.info("Hubo un error al crear la orden")
            _logger.info(str(e))
            raise ValidationError(_("There was an error creating the payment order"))

    def process_create_payment_order_qr_tramma(self, order):
        try:
            # Obtener fecha actual con zona horaria
            actual_date = datetime.now()

            # Agregar 5 minutos
            five_min_date = actual_date + timedelta(minutes=5)

            # Formatear la fecha con el formato específico
            formated_datetime = five_min_date.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "-04:00"

            url = self.get_create_qr_tramma_mp_endpoint()
            headers = self.get_headers_create_order_mp()
            body = self.get_body_create_order_mp(order)
            body["title"] = "Orden QR Dinamico"
            body["description"] = "Descripcion de orden"
            body["expiration_date"] = formated_datetime
            body["total_amount"] = sum(body['items'][i]['total_amount'] for i in range(len(body['items'])))

            # Enviamos la solicitud POST
            mp_user = self.store_branch_id.mp_user_id
            if mp_user:
                response = mp_user._make_request('post', url, json=body)
            else:
                response = requests.post(url, json=body, headers=headers)

            data = response.json()
            data["qr_data"] = qrcode.make(data["qr_data"])

            buffered = BytesIO()
            data["qr_data"].save(buffered, format="PNG")
            img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
            data["qr_data"] = f'data:image/png;base64,{img_str}'

            # Validamos si hubo un error al crear la sucursal
            if response.status_code >= 400:
                raise ValidationError(_("An error occurred while creating the payment order"))
            
            return data

        except Exception as e:
            
            _logger.info("Hubo un error al crear la orden")
            _logger.info(str(e))
            raise ValidationError(_("There was an error creating the payment order"))



    # get create order MercadoPago Endpoint
    def get_create_order_mp_endpoint(self):
        return f"https://api.mercadopago.com/mpmobile/instore/qr/{self.user_id_mp}/{self.external_id}"
    
    # get create QR Tramma MercadoPago Endpoint
    def get_create_qr_tramma_mp_endpoint(self):
        return f"https://api.mercadopago.com/instore/orders/qr/seller/collectors/{self.user_id_mp}/pos/{self.external_id}/qrs"
    
    def get_headers_create_order_mp(self):
        mp_user = self.store_branch_id.mp_user_id
        if mp_user:
            token = mp_user.access_token
        else:
            token = self.env.ref('pos_mercadopago.access_token_mercado_pago_conf').sudo().value
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "X-Ttl-Store-Preference": "300"
        }
    
    # Get body to create an order endpoint on mercado pago
    def get_body_create_order_mp(self, order):
        webUrl = self.env["ir.config_parameter"].sudo().search([("key","=","web.base.url")], limit=1).value
        return {
            "external_reference": order["external_reference"],
            "notification_url":f"{webUrl}/pos/mercadopago/notifications",
            # "sponsor_id": self.store_branch_id.sponsor_id,
            "items": order["items"]
        }
    
    # Get store till by id
    def get_store_till_by_id(self):
        param = self.env['ir.config_parameter'].sudo()
        qr_type = param.get_param('pos_mercadopago.mp_qr_type', default='static')
        return {
            "till":self.read()[0],
            "qr_type":qr_type
        }