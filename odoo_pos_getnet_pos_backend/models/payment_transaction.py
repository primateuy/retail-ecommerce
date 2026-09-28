# -*- coding: utf-8 -*-
"""
Enlace payment.transaction -> línea de pago del POS Backend, y la red que
recoge lo que quedó aprobado sin dueño.

La referencia la pone el POS y es lo ÚNICO que vuelve en la operación 3 del
contrato. Getnet identifica la transacción por su propio token, así que sin
este mapeo —guardado y commiteado antes de contestar— una línea pendiente
apuntaría a nada y el caso 1.4 del contrato (aprobó y no nos enteramos)
volvería a estar abierto.
"""

import logging

from odoo import _, api, fields, models

from odoo.addons.odoo_pos_getnet_core.models import getnet_utils

_logger = logging.getLogger(__name__)

# Tope de transacciones que mira cada pasada, por las mismas razones que el
# cron de recuperación del núcleo: una pasada acotada y frecuente envejece
# mejor que una que intenta resolver el mundo.
GETNET_HUERFANAS_BATCH = 20
# Un cobro aprobado SIN línea en el POS puede ser uno que el POS todavía está
# guardando. Pasado este margen ya no: la línea no va a llegar (típicamente
# Odoo murió entre el posteo y el guardado del pedido) y lo tiene que mirar
# una persona.
GETNET_HUERFANA_SIN_LINEA_SEGUNDOS = 15 * 60


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    getnet_transaction_origin = fields.Selection(
        selection_add=[('pos_backend', 'POS Backend')],
        ondelete={'pos_backend': 'set null'},
    )
    getnet_pos_backend_reference = fields.Char(
        string='Referencia del POS Backend',
        index=True,
        copy=False,
        help='La referencia que puso el POS al pedir la autorización. Es la '
             'llave con la que vuelve a preguntar por esta transacción, y con '
             'la que se la reencuentra con su línea de pago.',
    )
    getnet_pos_backend_line_id = fields.Many2one(
        comodel_name='pos_backend.order.payment.line',
        string='Línea de pago (POS Backend)',
        ondelete='set null',
        copy=False,
        index=True,
        help='Se completa cuando se reencuentra la línea por la referencia. '
             'No se puede llenar al autorizar: en ese momento la línea '
             'todavía no existe — el POS la crea con lo que contestamos.',
    )

    # ------------------------------------------------------------------
    def getnet_pos_backend_linea(self):
        """La línea de pago de esta transacción, buscándola por referencia.

        No se puede guardar el enlace al autorizar porque la línea todavía no
        existe: el POS la crea DESPUÉS, con el resultado que le devolvemos. El
        puente durable es la referencia, que la pone el POS y viaja en los dos
        sentidos. Cuando se la encuentra se deja anotada, para que la próxima
        pasada sea barata y para que una persona vea el vínculo.
        """
        self.ensure_one()
        if self.getnet_pos_backend_line_id:
            return self.getnet_pos_backend_line_id
        if not self.getnet_pos_backend_reference:
            return self.env['pos_backend.order.payment.line']
        linea = self.env['pos_backend.order.payment.line'].sudo().search([
            ('transaction_reference', '=', self.getnet_pos_backend_reference),
        ], limit=1, order='id desc')
        if linea:
            self.sudo().getnet_pos_backend_line_id = linea.id
        return linea

    # ------------------------------------------------------------------
    @api.model
    def _getnet_cron_recover_inflight(self):
        """Además de recuperar, deja al día las líneas del POS que esperaban."""
        res = super()._getnet_cron_recover_inflight()
        self._getnet_sincronizar_lineas_pos_backend()
        return res

    @api.model
    def _getnet_sincronizar_lineas_pos_backend(self):
        """Líneas del POS «sin confirmar» cuya transacción ya se resolvió.

        Pasado el tope del sondeo de la pantalla, el cobro queda en «no sé» y
        lo sigue el cron de recuperación. Cuando éste lo resuelve, la línea
        del pedido tiene que enterarse SOLA —sin que nadie toque Consultar—:
        aprobada pasa a autorizada con su ticket; rechazada o cancelada se
        descarta con el motivo de la terminal. Sólo líneas vivas: una línea
        ya cancelada con la transacción aprobada es una huérfana, y esa la
        resuelve el cron de huérfanos con una devolución.
        """
        lineas = self.env['pos_backend.order.payment.line'].sudo().search([
            ('integration_state', '=', 'pendiente'),
            ('state', '=', 'pendiente'),
            ('payment_method_id.terminal_provider', '=', 'getnet'),
            ('transaction_reference', '!=', False),
        ])
        for linea in lineas:
            tx = self.sudo().search([
                ('getnet_pos_backend_reference', '=', linea.transaction_reference),
                ('reference', 'not like', 'GETNET-PB-DEV-%'),
            ], order='id desc', limit=1)
            if not tx or tx.state not in ('done', 'cancel', 'error'):
                continue
            if tx.state == 'done':
                linea._workflow_write({
                    'integration_state': 'autorizado',
                    'transaction_id': tx.getnet_ticket or '',
                })
            else:
                linea._discard_transaction(
                    tx.getnet_msg_respuesta
                    or _('La terminal informó que la transacción no se aprobó.'))
            tx.getnet_pos_backend_line_id = linea
            getnet_utils.getnet_safe_commit(self.env)

    def _getnet_cron_reversar_huerfanas_pos_backend(self):
        """Reversa los cobros que quedaron APROBADOS y sin dueño.

        DE DÓNDE SALE ESTE CRON. Liberar un pedido consulta a la terminal y
        reversa lo aprobado (contrato §8.2), pero eso vale para lo que el POS
        alcanza a ver EN ESE MOMENTO. Quedan dos huecos que ninguna pantalla
        cubre:

          - la transacción estaba en «no sé» cuando se liberó —así que el
            pedido NO se liberó— pero el cron de recuperación del núcleo la
            resolvió después y salió APROBADA. Nadie va a volver a mirarla;
          - la línea se descartó (§7.2) creyendo que no había pasado nada, y
            la consulta posterior demostró que sí.

        En los dos casos hay plata cobrada en el pinpad contra una línea que
        ya no cuenta como cobro. Eso aparece en el cierre del adquirente sin
        nada que lo explique, y aparece días después.

        NO se reversa nada que el POS todavía pueda usar: sólo transacciones
        aprobadas cuya línea está CANCELADA. Una línea viva —aunque su pedido
        esté a medio cobrar— es un cobro legítimo en curso.

        Y si la reversa falla, la transacción se marca para conciliación
        manual en vez de reintentarse para siempre: reintentar una devolución
        a ciegas puede regalar el importe (contrato §7.3).
        """
        candidatas = self.search([
            ('provider_id.code', '=', 'getnet'),
            ('getnet_transaction_origin', '=', 'pos_backend'),
            ('state', '=', 'done'),
            ('getnet_requiere_conciliacion', '=', False),
            ('getnet_pos_backend_reference', '!=', False),
        ], limit=GETNET_HUERFANAS_BATCH, order='write_date asc')
        for tx in candidatas:
            linea = tx.getnet_pos_backend_linea()
            if not linea:
                # Sin línea no se puede afirmar que sea huérfana: puede que el
                # POS todavía no la haya creado. Se deja para la próxima...
                edad = (fields.Datetime.now() - tx.write_date).total_seconds()
                if edad < GETNET_HUERFANA_SIN_LINEA_SEGUNDOS:
                    continue
                # ...pero no para siempre. Pasado el margen, la línea no va a
                # llegar y el cajero seguramente ya cobró de nuevo: la clienta
                # pagó dos veces. NO se reversa a ciegas —no hay línea que
                # diga que este cobro sobra—: se marca y lo mira una persona.
                tx.getnet_marcar_conciliacion(_(
                    'Cobro aprobado (ticket %s) sin ninguna línea en el POS '
                    'Backend para la referencia %s: probablemente Odoo se '
                    'interrumpió entre el cobro y el guardado del pedido. '
                    'Verificar si el cliente pagó dos veces antes de '
                    'devolver.', tx.getnet_ticket or '-',
                    tx.getnet_pos_backend_reference))
                getnet_utils.getnet_safe_commit(self.env)
                continue
            if linea.state != 'cancelado':
                continue
            if linea.integration_state in ('reversado', 'devuelto'):
                # Ya se reversó: la línea lo dice. Nada que hacer.
                continue
            # Cada huérfana, aislada. Las candidatas se recorren por
            # antigüedad: si una revienta y corta la pasada, encabeza la fila
            # la vez siguiente y NINGUNA otra se reversa nunca más.
            try:
                with self.env.cr.savepoint():
                    self._getnet_reversar_huerfana(tx, linea)
            except Exception as error:  # noqa: BLE001 - se registra y se sigue
                _logger.exception(
                    'Getnet POS Backend: la reversa automática de %s falló.',
                    tx.reference)
                tx.getnet_marcar_conciliacion(_(
                    'La reversa automática de este cobro aprobado sobre una '
                    'línea cancelada falló con un error inesperado (%s). '
                    'Verificar contra el cierre del adquirente antes de '
                    'reintentar.', error))
            getnet_utils.getnet_safe_commit(self.env)

    def _getnet_reversar_huerfana(self, tx, linea):
        """Reversa una transacción aprobada cuya línea ya no cuenta."""
        if not tx.getnet_ticket:
            # Sin ticket no hay con qué pedir la reversa, y buscarla igual
            # termina en un «no se encontró la transacción» que no dice nada.
            # Una aprobada SIN ticket es rara —la consulta que la aprueba lo
            # persiste— así que se dice tal cual y la mira una persona.
            tx.getnet_marcar_conciliacion(_(
                'Cobro aprobado sobre una línea cancelada, pero la '
                'transacción no tiene número de ticket: no hay con qué pedir '
                'la reversa. Verificar contra el cierre del adquirente.'))
            return False
        terminal = linea.payment_method_id._get_terminal()
        if terminal is None:
            tx.getnet_marcar_conciliacion(_(
                'Cobro aprobado sobre una línea cancelada, y el medio %s se '
                'quedó sin terminal configurada: no hay a quién pedirle la '
                'reversa.', linea.payment_method_id.name))
            return False
        _logger.warning(
            'Getnet POS Backend: la transacción %s quedó APROBADA sobre una '
            'línea cancelada (%s, pedido %s). Se reversa.',
            tx.reference, linea.transaction_reference or '-',
            linea.order_id.name)
        respuesta = terminal.terminal_reverse(
            linea.payment_method_id, tx.getnet_ticket) or {}
        if not respuesta.get('ok'):
            tx.getnet_marcar_conciliacion(_(
                'Cobro aprobado sobre una línea cancelada y la reversa falló '
                '(%s). Verificar contra el cierre del adquirente antes de '
                'reintentar: una devolución repetida regala el importe.',
                respuesta.get('message') or _('sin motivo')))
            return False
        # La línea deja constancia de lo que pasó de verdad. No se borra nada.
        linea.sudo()._workflow_write({
            'integration_state': 'reversado',
            'discard_reason': _(
                'Reversada por el cron: la terminal había aprobado este cobro '
                'después de que la línea se cancelara.'),
        })
        return True
