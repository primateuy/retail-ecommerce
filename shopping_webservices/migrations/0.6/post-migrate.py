"""Migración 0.6: recalcula el Código Shopping de transacciones POS.

Las transacciones POS Manual quedaban sin código porque el cálculo buscaba el
pago POS por payment_transaction_id, que se enlaza después de crear la
transacción. Se recalculan las transacciones ligadas a un pago POS y se rehace
la distribución de las facturas que todavía no se declararon al shopping.
"""

import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
	"""Recalcula shopping_payment_code y la distribución de facturas pendientes.

	Args:
		cr: cursor de base de datos.
		version (str): versión instalada antes de actualizar.
	"""
	if not version:
		return
	env = api.Environment(cr, SUPERUSER_ID, {})
	transactions = env['payment.transaction'].search([('pos_payment_id', '!=', False)])
	env.add_to_compute(transactions._fields['shopping_payment_code'], transactions)
	transactions.flush_recordset(['shopping_payment_code'])
	_logger.info("Shopping 0.6: recalculado código en %s transacciones.", len(transactions))

	orders = env['pos.order'].search([
		('account_move.journal_id.integracionShopping', '=', True),
		('account_move.estadoEnvio', '!=', 'enviado'),
	])
	orders._refresh_shopping_payment_distribution()
	_logger.info("Shopping 0.6: distribución recalculada en %s pedidos.", len(orders))
