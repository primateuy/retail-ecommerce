from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from datetime import timedelta
import requests
import logging

_logger = logging.getLogger(__name__)


class MercadoPagoApplications(models.Model):

    _name = 'mercado_pago.applications'
    _description = 'Mercado Pago Applications'

    name = fields.Char(required=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
    )
    user_id = fields.Char(string='User ID', required=True)
    access_token = fields.Char(string='Access Token', required=True)
    client_id = fields.Char(string='Client ID', required=True)
    client_secret = fields.Char(string='Client Secret', required=True)

    token_refresh_days = fields.Integer(
        string='Refresh Token cada (dias)',
        default=170,
        help='Cantidad de dias entre cada renovacion automatica del access token. El token de MP vence cada 180 dias.',
    )
    token_last_refresh = fields.Datetime(
        string='Ultimo refresh de token',
        readonly=True,
    )

    store_branch_ids = fields.One2many(
        'store.branches',
        'application_id',
        string='Store Branches',
    )

    def _get_headers(self):
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }

    def refresh_access_token(self):
        self.ensure_one()
        url = "https://api.mercadopago.com/oauth/token"
        body = {
            "client_secret": self.client_secret,
            "client_id": self.client_id,
            "grant_type": "client_credentials",
        }
        try:
            response = requests.post(url, json=body, headers={"Content-Type": "application/json"})
            if response.status_code >= 400:
                raise ValidationError(
                    _("Error al refrescar el token de Mercado Pago: %s") % response.text
                )
            data = response.json()
            new_token = data.get("access_token")
            if not new_token:
                raise ValidationError(_("La respuesta de Mercado Pago no contiene access_token"))
            self.write({
                "access_token": new_token,
                "token_last_refresh": fields.Datetime.now(),
            })
            # Actualizar el token en los metodos de pago de PdV vinculados a ESTA aplicacion
            tills = self.store_branch_ids.store_tills_ids
            pos_configs = self.env['pos.config'].sudo().search([('mp_tills', 'in', tills.ids)])
            payment_methods = pos_configs.mapped('payment_method_ids').filtered(
                lambda pm: pm.use_payment_terminal == 'mercado_pago'
            )
            for pm in payment_methods:
                pm.write({'mp_bearer_token': new_token})
            _logger.info("Token refrescado correctamente para la aplicacion '%s' (ID: %s)", self.name, self.id)
        except requests.exceptions.RequestException as e:
            raise ValidationError(_("Error de conexion al refrescar token: %s") % str(e))

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Token actualizado"),
                "message": _("El access token fue renovado correctamente"),
                "type": "success",
                "sticky": False,
            }
        }

    @api.model
    def _cron_refresh_tokens(self):
        applications = self.search([])
        now = fields.Datetime.now()
        for app in applications:
            if app.token_last_refresh:
                next_refresh = app.token_last_refresh + timedelta(days=app.token_refresh_days)
                if now < next_refresh:
                    continue
            try:
                app.refresh_access_token()
            except Exception as e:
                _logger.error(
                    "Error al refrescar token para la aplicacion '%s' (ID: %s): %s",
                    app.name, app.id, str(e)
                )

    def fetch_stores_and_tills(self):
        self.ensure_one()
        headers = self._get_headers()

        # 1. Fetch stores from MP
        stores_url = f"https://api.mercadopago.com/users/{self.user_id}/stores/search"
        try:
            stores_response = requests.get(stores_url, headers=headers)
            if stores_response.status_code >= 400:
                raise ValidationError(
                    _("Error al obtener tiendas de Mercado Pago: %s") % stores_response.text
                )
            stores_data = stores_response.json()
        except requests.exceptions.RequestException as e:
            raise ValidationError(_("Error de conexion al obtener tiendas: %s") % str(e))

        mp_stores = stores_data.get("results", stores_data) if isinstance(stores_data, dict) else stores_data
        if not isinstance(mp_stores, list):
            mp_stores = []

        StoreBranch = self.env['store.branches']

        for store in mp_stores:
            mp_id = store.get("id")
            if not mp_id:
                continue

            location = store.get("location", {})
            vals = {
                "name": store.get("name", ""),
                "mp_store_branch_id": mp_id,
                "external_id": store.get("external_id", ""),
                "application_id": self.id,
                "street_number": location.get("street_number", ""),
                "street_name": location.get("address_line") or location.get("street_name", ""),
                "city_name": location.get("city_name", ""),
                "state_name": location.get("state_name", ""),
                "latitude": str(location.get("latitude", "0")),
                "longitude": str(location.get("longitude", "0")),
                "reference": location.get("reference", ""),
            }

            existing = StoreBranch.search([
                ("mp_store_branch_id", "=", mp_id)
            ], limit=1)

            if existing:
                existing.write(vals)
            else:
                # Bypass the default create that auto-generates external_id
                StoreBranch.with_context(skip_external_id=True).create(vals)

        # 2. Fetch tills/POS from MP
        tills_url = "https://api.mercadopago.com/pos"
        try:
            tills_response = requests.get(tills_url, headers=headers)
            if tills_response.status_code >= 400:
                raise ValidationError(
                    _("Error al obtener cajas de Mercado Pago: %s") % tills_response.text
                )
            tills_data = tills_response.json()
        except requests.exceptions.RequestException as e:
            raise ValidationError(_("Error de conexion al obtener cajas: %s") % str(e))

        mp_tills = tills_data.get("results", tills_data) if isinstance(tills_data, dict) else tills_data
        if not isinstance(mp_tills, list):
            mp_tills = []

        StoreTill = self.env['store.tills']

        for till in mp_tills:
            pos_id = till.get("id")
            if not pos_id:
                continue

            # Find the parent store branch by store_id from MP
            store_id_mp = till.get("store_id")
            parent_branch = StoreBranch.search([
                ("mp_store_branch_id", "=", store_id_mp),
                ("application_id", "=", self.id),
            ], limit=1)

            if not parent_branch:
                continue

            qr_data = till.get("qr", {})
            vals = {
                "name": till.get("name", ""),
                "store_branch_id": parent_branch.id,
                "fixed_amount": till.get("fixed_amount", True),
                "external_id": till.get("external_id", ""),
                "pos_id_mp": str(pos_id),
                "qr_url": qr_data.get("image", ""),
                "qr_template_document": qr_data.get("template_document", ""),
                "qr_template_image": qr_data.get("template_image", ""),
                "qr_code": till.get("qr_code", ""),
                "uuid_mp": till.get("uuid", ""),
                "user_id_mp": str(till.get("user_id", "")),
                "status_mp": till.get("status", ""),
            }

            # Map category from MP integer to selection
            category_val = till.get("category")
            if category_val:
                service_code = self.env.ref(
                    'pos_mercadopago.service_category_code_conf'
                ).sudo().value
                gastronomy_code = self.env.ref(
                    'pos_mercadopago.gastronomy_category_code_conf'
                ).sudo().value
                if str(category_val) == str(service_code):
                    vals["category"] = "service"
                elif str(category_val) == str(gastronomy_code):
                    vals["category"] = "gastronomy"

            existing_till = StoreTill.search([
                ("pos_id_mp", "=", str(pos_id))
            ], limit=1)

            if existing_till:
                existing_till.write(vals)
            else:
                StoreTill.with_context(skip_mp_create=True).create(vals)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Importacion completada"),
                "message": _("Tiendas y cajas importadas correctamente desde Mercado Pago"),
                "type": "success",
                "sticky": False,
            }
        }
