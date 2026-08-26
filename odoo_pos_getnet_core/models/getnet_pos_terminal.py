# -*- coding: utf-8 -*-
"""
Modelo: terminales POS Getnet/TransAct (TermCod) asociadas a un
payment.provider, con lock de exclusión mutua cross-flujo.

Invariante del core: el posteo estándar de TransAct es SERIAL por TermCod —
postear una segunda factura cancela la anterior y solo se puede confirmar la
última. Si el backend contable y el TPV comparten un mismo pinpad, no alcanza
con que cada flujo sea internamente serial: la exclusión debe abarcar ambos.
Todo flujo que postee a una terminal DEBE tomar el lock con getnet_claim()
antes de PostearTransaccion y liberarlo con getnet_release() al terminar
(éxito, error o cancelación).
"""

import logging

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Un claim más viejo que esto se considera huérfano (worker muerto sin
# liberar) y puede ser tomado por otro flujo. El worker de polling debe
# refrescar el lock con getnet_touch() en cada iteración, así un flujo vivo
# nunca vence aunque el polling se extienda (caso cancel fallido).
GETNET_LOCK_TTL_SECONDS = 600
# Heartbeat: el touch del polling ocurre en cada iteración (<= 15s). Un lock
# cuyo touch tiene más de esto se considera de un hilo MUERTO aunque el TTL
# del claim no haya vencido; lo usa el cron de recuperación para distinguir
# transacciones con hilo vivo (se saltean) de huérfanas (se recuperan).
GETNET_HEARTBEAT_SECONDS = 120


class GetnetPosTerminal(models.Model):
    """
    Terminal física / POS identificada por TermCod para integración TransAct.

    Utilizada para: enrutar el cobro cuando el proveedor tiene múltiples
    terminales, y para serializar el acceso al pinpad entre flujos.
    """

    _name = 'getnet.pos.terminal'
    _description = 'Terminal Getnet TransAct (TermCod)'

    name = fields.Char(
        string='Alias',
        required=True,
        help='Nombre descriptivo para identificar la terminal en listas.',
    )
    term_cod = fields.Char(
        string='TermCod',
        required=True,
        size=6,
        help='Código de terminal asignado por New Age Data (TransAct). '
             'Largo 6, ej. T00001.',
    )
    payment_provider_id = fields.Many2one(
        comodel_name='payment.provider',
        string='Proveedor Getnet',
        required=True,
        ondelete='cascade',
        domain="[('code', '=', 'getnet')]",
    )
    lock_origin = fields.Char(
        string='Ocupada por',
        copy=False,
        help='Flujo que tiene tomada la terminal (account_payment / pos / '
             'cierre_lote). Vacío = libre.',
    )
    lock_ref = fields.Char(
        string='Referencia del lock',
        copy=False,
        help='Token o referencia de la operación en curso.',
    )
    lock_uid = fields.Many2one(
        comodel_name='res.users',
        string='Usuario del lock',
        copy=False,
    )
    lock_date = fields.Datetime(
        string='Lock desde',
        copy=False,
    )

    _sql_constraints = [
        (
            'term_cod_provider_uniq',
            'unique(term_cod, payment_provider_id)',
            'Ya existe una terminal con ese TermCod para este proveedor.',
        ),
    ]

    def getnet_claim(self, origin, ref=''):
        """
        Toma la terminal para un flujo, en forma atómica (UPDATE condicional
        a nivel SQL, seguro entre workers). Falla con UserError si otro flujo
        la tiene tomada y su lock no venció.

        IMPORTANTE: el claim se vuelve visible para otros workers recién al
        commit de la transacción. El flujo llamador debe commitear el claim
        antes de PostearTransaccion (mismo patrón que el flag async de
        Fiserv: write + flush + commit antes de lanzar el hilo).

        Se usa clock_timestamp() y no now(): now() devuelve el inicio de
        la transacción, y en transacciones largas el lock nacería "viejo"
        para el heartbeat/TTL.
        """
        self.ensure_one()
        self.env.cr.execute(
            """
            UPDATE getnet_pos_terminal
               SET lock_origin = %s,
                   lock_ref = %s,
                   lock_uid = %s,
                   lock_date = (clock_timestamp() AT TIME ZONE 'UTC')
             WHERE id = %s
               AND (
                   lock_origin IS NULL
                   OR lock_date < (clock_timestamp() AT TIME ZONE 'UTC')
                                  - make_interval(secs => %s)
               )
         RETURNING id
            """,
            (origin, ref or '', self.env.uid, self.id,
             GETNET_LOCK_TTL_SECONDS),
        )
        claimed = self.env.cr.fetchall()
        self.invalidate_recordset(
            ['lock_origin', 'lock_ref', 'lock_uid', 'lock_date'])
        if not claimed:
            raise UserError(_(
                'La terminal %(terminal)s está ocupada por otra operación '
                '(%(origin)s%(ref)s) iniciada el %(date)s. Espere a que '
                'termine o pida a un administrador liberar la terminal.',
                terminal=self.display_name,
                origin=self.lock_origin or '?',
                ref=(' / %s' % self.lock_ref) if self.lock_ref else '',
                date=self.lock_date or '?',
            ))
        return True

    def getnet_touch(self):
        """
        Refresca el lock durante el polling para que un flujo vivo nunca
        venza por TTL. Idempotente y sin condiciones: solo el dueño del lock
        llama a touch.
        """
        self.ensure_one()
        self.env.cr.execute(
            """
            UPDATE getnet_pos_terminal
               SET lock_date = (clock_timestamp() AT TIME ZONE 'UTC')
             WHERE id = %s AND lock_origin IS NOT NULL
            """,
            (self.id,),
        )

    def getnet_heartbeat_alive(self, ref, seconds=GETNET_HEARTBEAT_SECONDS):
        """
        True si la terminal está tomada por la operación ``ref`` y su lock
        fue refrescado (touch) hace menos de ``seconds``: señal de que el
        hilo de polling de esa operación sigue vivo.
        """
        self.ensure_one()
        if not self.lock_origin or self.lock_ref != ref or not self.lock_date:
            return False
        delta = fields.Datetime.now() - self.lock_date
        return delta.total_seconds() < seconds

    def getnet_release(self):
        """Libera la terminal. Idempotente (liberar libre no es error)."""
        self.ensure_one()
        self.env.cr.execute(
            """
            UPDATE getnet_pos_terminal
               SET lock_origin = NULL,
                   lock_ref = NULL,
                   lock_uid = NULL,
                   lock_date = NULL
             WHERE id = %s
            """,
            (self.id,),
        )
        self.invalidate_recordset(
            ['lock_origin', 'lock_ref', 'lock_uid', 'lock_date'])

    def action_getnet_force_release(self):
        """
        Liberación manual explícita (acción de administrador). Deja rastro en
        el log: forzar la liberación con una operación realmente en vuelo
        puede dejar un cobro aprobado en el pinpad sin pago en Odoo.
        """
        self.ensure_one()
        _logger.warning(
            'Getnet: liberación FORZADA de la terminal %s (lock previo: '
            'origin=%s ref=%s uid=%s desde=%s) por el usuario %s (id %s).',
            self.display_name, self.lock_origin, self.lock_ref,
            self.lock_uid.id if self.lock_uid else None, self.lock_date,
            self.env.user.name, self.env.uid,
        )
        self.getnet_release()
