# -*- coding: utf-8 -*-
from odoo import _, fields, models
from odoo.exceptions import UserError


class PosSession(models.Model):
    _inherit = "pos.session"

    def _pos_ui_models_to_load(self):
        """
        Extiende los modelos a cargar en el POS para incluir razones de movimiento.

        Returns:
            list: Lista de modelos a cargar en la UI del POS.
        """
        # Obtener la lista base de modelos a cargar
        result = super()._pos_ui_models_to_load()
        # Agregar el modelo de razones si aún no está incluido
        if "pos.move.reason" not in result:
            result.append("pos.move.reason")
        # Devolver la lista final de modelos
        return result

    def _loader_params_pos_move_reason(self):
        """
        Define los parámetros de carga de razones de movimiento para la UI.

        Returns:
            dict: Parámetros de búsqueda para las razones de movimiento.
        """
        # Garantizar que se trabaje con una sola sesión
        self.ensure_one()
        # Construir el dominio por compañía y registros activos
        domain = [("company_id", "=", self.company_id.id), ("active", "=", True)]
        # Definir los campos mínimos necesarios para el POS
        fields_to_load = ["name", "is_income_reason", "is_expense_reason", "company_id"]
        # Devolver la estructura esperada por el loader del POS
        return {
            "search_params": {
                "domain": domain,
                "fields": fields_to_load,
            },
        }

    def _get_pos_ui_pos_move_reason(self, params):
        """
        Obtiene las razones de movimiento para la UI del POS.

        Args:
            params (dict): Parámetros de búsqueda con dominio y campos.

        Returns:
            list: Lista de razones de movimiento con sus campos.
        """
        # Ejecutar la búsqueda con los parámetros recibidos
        reasons = self.env["pos.move.reason"].search_read(**params["search_params"])
        # Retornar la lista para el frontend
        return reasons

    def _loader_params_pos_config(self):
        """
        Extiende la carga de pos.config para incluir las razones habilitadas.

        Returns:
            dict: Parámetros de carga extendidos para pos.config.
        """
        # Obtener los parámetros base del POS
        result = super()._loader_params_pos_config()
        # Validar estructura antes de modificar la lista de campos
        if (
            result
            and isinstance(result, dict)
            and "search_params" in result
            and "fields" in result["search_params"]
            and isinstance(result["search_params"]["fields"], list)
            and len(result["search_params"]["fields"]) > 0
        ):
            # Agregar el campo de razones si aún no está presente
            if "cash_move_reason_ids" not in result["search_params"]["fields"]:
                result["search_params"]["fields"].append("cash_move_reason_ids")
        # Retornar los parámetros extendidos
        return result

    def try_cash_in_out(self, _type, amount, reason, extras, move_reason_id=False):
        """
        Crea un movimiento de caja con razón configurada si se proporciona.

        Args:
            _type (str): Tipo de movimiento ('in' o 'out').
            amount (float): Monto del movimiento.
            reason (str): Texto libre de razón o comentario.
            extras (dict): Datos adicionales de UI para referencia.
            move_reason_id (int|bool): ID de pos.move.reason si aplica.
        """
        # Si no hay razón configurada, usar la lógica estándar
        if not move_reason_id:
            return super().try_cash_in_out(_type, amount, reason, extras)

        # Validar sesión con journal de caja configurado
        sessions = self.filtered("cash_journal_id")
        if not sessions:
            raise UserError(_("There is no cash payment method for this PoS Session"))

        # Validar razón configurada y su compañía
        move_reason = self.env["pos.move.reason"].browse(move_reason_id).exists()
        if not move_reason or move_reason.company_id != self.company_id:
            raise UserError(_("Invalid cash move reason for this company."))

        # Validar tipo de razón según el movimiento solicitado
        if _type == "in" and not move_reason.is_income_reason:
            raise UserError(_("The selected reason is not valid for cash in."))
        if _type == "out" and not move_reason.is_expense_reason:
            raise UserError(_("The selected reason is not valid for cash out."))

        # Determinar cuenta contraparte según el tipo de movimiento
        if _type == "in":
            account_id = move_reason.income_account_id.id
            signed_amount = amount
        else:
            account_id = move_reason.expense_account_id.id
            signed_amount = -amount

        # Validar que exista cuenta para el tipo de movimiento
        if not account_id:
            raise UserError(_("The selected reason has no account configured."))

        # Asegurar que el journal de caja esté habilitado en la razón
        if move_reason.journal_ids and sessions:
            invalid_sessions = sessions.filtered(
                lambda s: s.cash_journal_id not in move_reason.journal_ids
            )
            if invalid_sessions:
                raise UserError(
                    _("The selected reason is not allowed for the cash journal in this POS.")
                )

        # Construir la referencia de pago usando razón y datos extra
        reason_name = reason.strip() or move_reason.name
        translated_type = extras.get("translatedType", _type) if isinstance(extras, dict) else _type
        payment_ref = f"{sessions[0].name} - {translated_type} - {reason_name}"

        # Crear líneas de extracto con cuenta contraparte
        self.env["account.bank.statement.line"].create(
            [
                {
                    "pos_session_id": session.id,
                    "journal_id": session.cash_journal_id.id,
                    "amount": signed_amount,
                    "date": fields.Date.context_today(self),
                    "payment_ref": payment_ref,
                    "counterpart_account_id": account_id,
                }
                for session in sessions
            ]
        )
