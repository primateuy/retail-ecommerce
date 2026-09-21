from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from datetime import timedelta
import requests
import logging

_logger = logging.getLogger(__name__)

# Maximo de registros por pagina que admite la API de Mercado Pago.
MP_PAGE_SIZE = 30


class MercadoPagoUser(models.Model):

    _name = 'mercado_pago.user'
    _description = 'Mercado Pago User'

    name = fields.Char(required=True)
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
    )
    user_id = fields.Char(string='User ID', required=True)
    access_token = fields.Char(
        string='Access Token',
        required=True,
        groups='base.group_system',
        copy=False,
    )

    token_refresh_hours = fields.Integer(
        string='Refresh Token cada (horas)',
        default=5,
        help='Cantidad de horas entre cada renovacion automatica del access token. El token de MP dura aproximadamente 6 horas.',
    )
    token_last_refresh = fields.Datetime(
        string='Ultimo refresh de token',
        readonly=True,
    )

    applications_ids = fields.One2many(
        'mercado_pago.applications',
        'mp_user_id',
        string='Aplicaciones',
    )
    store_branch_ids = fields.One2many(
        'store.branches',
        'mp_user_id',
        string='Tiendas',
    )

    def _get_headers(self):
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }

    def _make_request(self, method, url, **kwargs):
        """Realiza una request HTTP. Si recibe 401, refresca el token y reintenta una vez."""
        self.ensure_one()
        kwargs.setdefault('headers', self._get_headers())
        response = getattr(requests, method)(url, **kwargs)
        if response.status_code == 401:
            _logger.warning("Token expirado para usuario '%s', refrescando y reintentando...", self.name)
            try:
                self.with_context(auto_refresh=True).refresh_access_token()
            except Exception as e:
                _logger.error("Error al refrescar token: %s", str(e))
                return response
            kwargs['headers'] = self._get_headers()
            response = getattr(requests, method)(url, **kwargs)
        return response

    def refresh_access_token(self):
        self.ensure_one()
        app = self.applications_ids[:1]
        if not app:
            raise ValidationError(_("No hay aplicaciones (credenciales) configuradas para este usuario"))
        url = "https://api.mercadopago.com/oauth/token"
        body = {
            "client_secret": app.client_secret,
            "client_id": app.client_id,
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
            # Actualizar el token en los metodos de pago de PdV vinculados a este usuario
            tills = self.store_branch_ids.store_tills_ids
            pos_configs = self.env['pos.config'].sudo().search([('mp_tills', 'in', tills.ids)])
            payment_methods = pos_configs.mapped('payment_method_ids').filtered(
                lambda pm: pm.use_payment_terminal == 'mercado_pago'
            )
            for pm in payment_methods:
                try:
                    pm.write({'mp_bearer_token': new_token})
                except Exception as e:
                    if self.env.context.get('auto_refresh'):
                        _logger.warning(
                            "No se pudo actualizar mp_bearer_token en el metodo de pago '%s': %s. "
                            "Cerrar la sesion POS activa para aplicar el cambio.",
                            pm.name, str(e)
                        )
                    else:
                        raise
            _logger.info("Token refrescado correctamente para el usuario '%s' (ID: %s)", self.name, self.id)
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
        users = self.search([])
        now = fields.Datetime.now()
        for user in users:
            if user.token_last_refresh:
                next_refresh = user.token_last_refresh + timedelta(hours=user.token_refresh_hours)
                if now < next_refresh:
                    continue
            try:
                user.with_context(auto_refresh=True).refresh_access_token()
            except Exception as e:
                _logger.error(
                    "Error al refrescar token para el usuario '%s' (ID: %s): %s",
                    user.name, user.id, str(e)
                )

    def _fetch_all_paginated(self, url, resource_label, page_size=MP_PAGE_SIZE):
        """Obtiene todos los resultados de un endpoint paginado de Mercado Pago.

        Los endpoints de tiendas y cajas devuelven como maximo ``page_size``
        registros por request, junto con un bloque ``paging`` con el ``total``.
        Este metodo itera incrementando ``offset`` hasta cubrir el total (o hasta
        que una pagina venga incompleta, si la respuesta no trae ``paging``).

        Args:
            url (str): endpoint a consultar (sin parametros de paginacion).
            resource_label (str): nombre del recurso para los mensajes de error.
            page_size (int): cantidad de registros por pagina.

        Returns:
            list: todos los registros acumulados de ``results``.

        Raises:
            ValidationError: si la API responde con error o falla la conexion.
        """
        self.ensure_one()
        results = []
        offset = 0
        total = None
        while True:
            params = {"offset": offset, "limit": page_size}
            try:
                response = self._make_request('get', url, params=params)
                if response.status_code >= 400:
                    raise ValidationError(
                        _("Error al obtener %s de Mercado Pago: %s") % (resource_label, response.text)
                    )
                data = response.json()
            except requests.exceptions.RequestException as e:
                raise ValidationError(
                    _("Error de conexion al obtener %s: %s") % (resource_label, str(e))
                )

            if isinstance(data, dict):
                page = data.get("results", [])
                paging = data.get("paging") or {}
                total = paging.get("total", total)
            else:
                page = data
            if not isinstance(page, list):
                page = []

            results.extend(page)
            offset += page_size

            # Sin paging: cortamos cuando la pagina viene vacia o incompleta.
            if not page or len(page) < page_size:
                break
            if total is not None and offset >= total:
                break

        _logger.info("Mercado Pago: %s %s obtenidas desde %s", len(results), resource_label, url)
        return results

    def fetch_stores_and_tills(self):
        self.ensure_one()

        # 1. Fetch stores from MP
        stores_url = f"https://api.mercadopago.com/users/{self.user_id}/stores/search"
        mp_stores = self._fetch_all_paginated(stores_url, _("tiendas"))

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
                "mp_user_id": self.id,
                "street_number": location.get("street_number", ""),
                "street_name": location.get("address_line") or location.get("street_name", ""),
                "city_name": location.get("city_name", ""),
                "state_name": location.get("state_name", ""),
                "latitude": str(location.get("latitude", "0")),
                "longitude": str(location.get("longitude", "0")),
                "reference": location.get("reference", ""),
            }

            existing = StoreBranch.search([("mp_store_branch_id", "=", mp_id)], limit=1)
            if existing:
                # No sobreescribir mp_user_id si ya tiene uno asignado
                update_vals = {k: v for k, v in vals.items() if k != 'mp_user_id'}
                existing.write(update_vals)
            else:
                StoreBranch.with_context(skip_external_id=True).create(vals)

        # 2. Fetch tills/POS from MP
        tills_url = "https://api.mercadopago.com/pos"
        mp_tills = self._fetch_all_paginated(tills_url, _("cajas"))

        StoreTill = self.env['store.tills']

        for till in mp_tills:
            pos_id = till.get("id")
            if not pos_id:
                continue

            store_id_mp = till.get("store_id")
            parent_branch = StoreBranch.search([
                ("mp_store_branch_id", "=", store_id_mp),
                ("mp_user_id", "=", self.id),
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

            category_val = till.get("category")
            if category_val:
                service_code = self.env.ref('pos_mercadopago.service_category_code_conf').sudo().value
                gastronomy_code = self.env.ref('pos_mercadopago.gastronomy_category_code_conf').sudo().value
                if str(category_val) == str(service_code):
                    vals["category"] = "service"
                elif str(category_val) == str(gastronomy_code):
                    vals["category"] = "gastronomy"

            existing_till = StoreTill.search([("pos_id_mp", "=", str(pos_id))], limit=1)
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
