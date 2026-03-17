import logging
from odoo import _, api, fields, models, tools
from odoo.exceptions import AccessError, UserError
from odoo.addons.pos_mercado_pago.models.mercado_pago_pos_request import MercadoPagoPosRequest
_logger = logging.getLogger(__name__)

class PosPaymentMethod(models.Model):

    _inherit = 'pos.payment.method'

    qr_integration = fields.Boolean(default=False, string="QR Integration")

    def write(self, vals):
        return super().write(vals)


class PosSession(models.Model):
    _inherit = 'pos.session'

    def _loader_params_pos_payment_method(self):
        result = super()._loader_params_pos_payment_method()
        result['search_params']['fields'].append('qr_integration')
        return result
    
    def _find_terminal(self, token, point_smart):
        if self.mp_id_point_smart:
            mercado_pago = MercadoPagoPosRequest(token)
            data = mercado_pago.call_mercado_pago("get", "/point/integration-api/devices", {})
            if 'devices' in data:
                # Search for a device id that contains the serial number entered by the user
                found_device = next((device for device in data['devices'] if point_smart in device['id']), None)

                if not found_device:
                    raise UserError(_("The terminal serial number is not registered on Mercado Pago"))

                return found_device.get('id', '')
            else:
                raise UserError(_("Please verify your production user token as it was rejected"))
