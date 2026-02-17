from odoo import _, api, fields, models, tools
from odoo.exceptions import ValidationError
import requests
import logging

_logger = logging.getLogger(__name__)

class StoreBranches(models.Model):

    _name = 'store.branches'
    _description = 'Branches of stores'

    name = fields.Char(required=True)
    external_id = fields.Char()

    business_hours_ids = fields.One2many(
        'business.hours', 
        'store_branch_id', 
        required=True
    )
    mp_store_branch_id = fields.Integer()

    # Location
    street_number = fields.Char()
    street_name = fields.Char()
    city_name = fields.Char()
    state_name = fields.Char()
    latitude = fields.Char()
    longitude = fields.Char()
    reference = fields.Char()

    # Application
    application_id = fields.Many2one(
        'mercado_pago.applications',
        string='Application',
    )

    # Store tills
    store_tills_ids = fields.One2many(
        'store.tills',
        'store_branch_id',
        required=True
    )

    @api.model
    def create(self, values):
        result = super().create(values)
        if not self.env.context.get('skip_external_id') and not values.get('external_id'):
            result.write({
                "external_id": result.generate_external_id()
            })
        return result

    # Generamos el id externo
    def generate_external_id(self):
        return f"STORE{self.id}"

    # Create a store branch with Mercado Pago API
    def create_store_branch_mp(self):
        try:
            # Validamos si ya esta registrado
            if self.mp_store_branch_id:
                raise ValidationError(_("This branch is already registered in Mercado Pago"))
            
            # Prepare request
            headers = self.get_endpoint_headers()
            body = self.get_endpoint_store_branch_body()
            url = self.get_endpoint_route()

            # Enviamos la solicitud POST
            response = requests.post(url, json=body, headers=headers)

            # Validamos si hubo un error al crear la sucursal
            if response.status_code >= 400:
                raise ValidationError(_("Ha ocurrido un error al crear la sucursal"))
            
            data = response.json()
            self.write({
                "mp_store_branch_id": data["id"]
            })
            
            return {
                "value":{},
                "warning":{
                    "title": "Creacion de la sucursal",
                    "message": "Sucursal creada correctamente"
                }
            }
        except Exception as e:
            _logger.info("Ocurrio un error al crear la sucursal")
            _logger.info(str(e))
            raise ValidationError(_("Ha ocurrido un error al crear la sucursal"))

    def get_endpoint_route(self):
        if self.application_id:
            user_id = self.application_id.user_id
        else:
            user_id = self.env.ref('pos_mercadopago.user_id_mercado_pago_conf').sudo().value
        return f"https://api.mercadopago.com/users/{user_id}/stores"

    def get_endpoint_headers(self):
        if self.application_id:
            token = self.application_id.access_token
        else:
            token = self.env.ref('pos_mercadopago.access_token_mercado_pago_conf').sudo().value
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }

    # Obtener el body que sera enviado en la peticion para crear la sucursal
    def get_endpoint_store_branch_body(self):
        return {
            "name": self.name,
            "business_hours": self.prepare_business_hours(),
            "external_id": self.external_id,
            "location": self.get_location()
        }

    # Obtener la lista de horarios laborales como lo necesita recibir el endpoint
    def prepare_business_hours(self):
        # Validamos si hay horarios registrados
        if len(self.business_hours_ids) == 0:
            raise ValidationError(_("You must add at least one business hour"))

        # Organizamos los horarios en un diccionario
        days = {}
        for record in self.business_hours_ids:
            days[record.day] = [
                {
                    "open": record.open_hour,
                    "close": record.close_hour
                }
            ]

        return days

    # Return a dictionario with the location info
    def get_location(self):
        return {
            "street_number": self.street_number,
            "street_name": self.street_name,
            "city_name": self.city_name,
            "state_name": self.state_name,
            "latitude": float(self.latitude),
            "longitude": float(self.longitude),
            "reference": self.reference
        }