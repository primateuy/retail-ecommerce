from odoo import _, api, fields, models, tools
import requests
import logging

_logger = logging.getLogger(__name__)

class PointOfSalesMercadoPago(models.Model):

    _name = 'point.of.sales.mercado.pago'
    _description = 'Modelo para guardar la informacion de los pos de mercado pago'

    active = fields.Boolean(default=True)
    name = fields.Char(required=True)
    external_store_id = fields.Char(required=True)
    external_id = fields.Char(required=True)
    category = fields.Integer(required=True)
    fixed_amount = fields.Boolean()
    payment_method_id = fields.Many2one(
        'pos.payment.method',
        string='Payment Method',
        domain="[('use_payment_terminal','=','mercado_pago')]",
        required=True
    )

    pos_id = fields.Char(string="POS id")
    pos_qr_url = fields.Char(string="QR url")

    # "name": "Caja Principal",
    # "fixed_amount": false,
    # "category": 621102,
    # "external_store_id": "sucursal_001",
    # "external_id": "caja_001"

    def create_pos_mercado_pago(self):

        # Reemplazá con tu Access Token real (preferiblemente el de producción si es para producción)
        ACCESS_TOKEN = self.payment_method_id.mp_bearer_token

        # Headers con el token de autenticación
        headers = {
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "Content-Type": "application/json"
        }

        # Datos del Punto de Venta (POS)
        data = {
            "name": self.name,
            "fixed_amount": self.fixed_amount,  # True si querés que el QR tenga un monto fijo
            "category": self.category,      # Código de categoría (ejemplo: 621102 para "Otros servicios personales n.c.p.")
            "external_store_id": self.external_store_id,
            "external_id": self.external_id
        }

        # URL de creación del punto de venta
        url = "https://api.mercadopago.com/pos"

        # Enviamos la solicitud POST
        response = requests.post(url, json=data, headers=headers)