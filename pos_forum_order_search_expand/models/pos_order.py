# -*- coding: utf-8 -*-
from odoo import api, models


class PosOrder(models.Model):
    _inherit = "pos.order"

    @api.model
    def search_paid_order_ids(self, config_id, domain, limit, offset):
        """
        Extiende la búsqueda de órdenes pagadas para quitar la restricción
        de compañía, manteniendo la lógica estándar de Odoo (mismo POS/config
        y misma moneda que el POS actual).

        Por qué sudo en vez de ampliar el contexto multi-company:
        la rule de core `point_of_sale.rule_pos_multi_company` aplica el
        filtro `('company_id','in', company_ids)`, donde `company_ids` se
        resuelve desde `context.allowed_company_ids` y, en su defecto, desde
        `user.company_ids.ids`. Para usuarios PDV de sucursal -que tienen
        UNA SOLA company asignada- ampliar el contexto no agrega nada: solo
        pueden poner ahí lo que tienen. El sudo() bypassea esa rule y permite
        ver órdenes de toda la organización desde el POS, sin necesidad de
        asignar más companies al usuario en el backend.

        Riesgos asumidos: el frontend del POS puede recibir órdenes de
        otras companies/sucursales; los métodos de pago de esas órdenes
        pueden no estar cargados en la sesión actual (la búsqueda del super
        ya filtra por mismo config_id y misma currency, así que el riesgo
        es acotado).
        """
        # sudo() bypassa la rule multi-company de core; el resto de los
        # filtros (config_id, currency, dominio del frontend) viaja por el super.
        return super(PosOrder, self.sudo()).search_paid_order_ids(
            config_id, domain, limit, offset)

    def export_for_ui(self):
        """
        Exporta órdenes para la UI usando sudo() para que el cajero pueda
        leer órdenes de otras companies devueltas por search_paid_order_ids.

        Sin esto, los ids devueltos por el sudo() de arriba serían inválidos
        al intentar leerlos como el usuario real (rule multi-company sigue
        aplicando en el read).
        """
        return super(PosOrder, self.sudo()).export_for_ui()

    # ------------------------------------------------------------------
    # Devolución de una orden hecha en otra sucursal
    #
    # Buscar y cargar el ticket ajeno ya funcionaba con los dos sudo() de
    # arriba. Lo que fallaba era VALIDAR la devolución: el flujo de creación
    # vuelve a leer la orden original y salta
    #
    #     AccessError: ... no tiene acceso 'leer' a: Órdenes del Punto de
    #     venta (pos.order)
    #
    # Hay dos reglas distintas que bloquean esa lectura:
    #
    # - `pos_restrict.order_user` (grupo PdV/Usuario) la acota a
    #   `config_id in user.allowed_pos.ids`  -> rompe entre sucursales de la
    #   misma empresa.
    # - `point_of_sale.pos_order_comp_rule` (regla global) la acota a
    #   `company_id in company_ids`          -> rompe entre empresas. Al ser
    #   global se combina con AND, así que no hay forma de abrirla con otra
    #   ir.rule: la única salida es sudo().
    #
    # Por eso el sudo va acotado a los métodos que necesitan la orden
    # original, y NO se toca ninguna ir.rule: el cajero sigue sin poder
    # escribir órdenes de otras cajas ni verlas en el backend.
    # ------------------------------------------------------------------

    def _compute_refund_related_fields(self):
        """Resuelve `refunded_order_ids` aunque la orden original sea de otra caja.

        Navega `lines.refunded_orderline_id.order_id`, que en una devolución
        entre sucursales apunta a una orden que el cajero no puede leer.
        """
        return super(PosOrder, self.sudo())._compute_refund_related_fields()

    def _compute_order_name(self):
        """Arma el nombre "<orden original> REEMBOLSO", que lee `refunded_order_ids.name`.

        Sin sudo el AccessError se lo termina comiendo `_process_saved_order`
        (hace `except Exception: _logger.error(...)`), así que la devolución
        entre empresas quedaba en borrador, con nombre "/" y sin aviso al
        cajero.
        """
        return super(PosOrder, self.sudo())._compute_order_name()

    def _is_pos_order_paid(self):
        """Compara contra los importes de la orden original en el reembolso total."""
        return super(PosOrder, self.sudo())._is_pos_order_paid()

    def _prepare_invoice_vals(self):
        """Arma la nota de crédito leyendo la factura de la orden original.

        Se propaga la zona horaria del usuario real en el contexto: core
        calcula `invoice_date` con `self.env.user.tz` y bajo sudo ese usuario
        pasa a ser OdooBot (sin tz), lo que podría correr un día la fecha de
        la factura.

        Entre empresas, el `reversed_entry_id` que arma core se descarta
        después en `account_move.create` de este mismo módulo, por el
        check_company de Odoo.
        """
        self.ensure_one()
        contexto = {"tz": self._context.get("tz") or self.env.user.tz}
        return super(
            PosOrder, self.sudo().with_context(**contexto)
        )._prepare_invoice_vals()


class PosOrderLine(models.Model):
    _inherit = "pos.order.line"

    def _compute_refund_qty(self):
        """Calcula la cantidad ya devuelta aunque la devolución sea de otra caja.

        Sin esto la línea original nunca queda marcada como devuelta para el
        cajero de la otra sucursal, y el mismo artículo se podría devolver
        más de una vez.
        """
        return super(PosOrderLine, self.sudo())._compute_refund_qty()
