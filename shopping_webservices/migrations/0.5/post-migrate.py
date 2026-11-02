"""Migración 0.5: los datos del shopping pasan del diario a la sucursal DGI.

Los campos del diario quedaron como relacionados no almacenados, pero Odoo no
borra sus columnas ni la tabla de formas de pago, así que los valores viejos
siguen disponibles para copiarlos. Se toma como fuente, por sucursal, el
diario con integración y mayor secuencial: el secuencial es por contrato y
el más alto es el más cercano al que espera el shopping.
"""

import logging

_logger = logging.getLogger(__name__)

SHOPPING_COLUMNS = {
	'tecnologia': 'shopping_technology',
	'url': 'shopping_url',
	'usuario': 'shopping_user',
	'password': 'shopping_password',
	'homologacion': 'is_shopping_homologation',
	'"codigoShopping"': 'shopping_code',
	'"nroContrato"': 'shopping_contract_number',
	'"codigoCanal"': 'shopping_channel_code',
	'caja': 'shopping_cash_register',
	'"codigoRubro"': 'shopping_category_code',
	'secuencial_ventas': 'shopping_sales_sequence',
}


def _column_exists(cr, table, column):
	"""Indica si la columna existe en la tabla.

	Args:
		cr: cursor de base de datos.
		table (str): nombre de la tabla.
		column (str): nombre de la columna, sin comillas.

	Returns:
		bool: True si la columna existe.
	"""
	cr.execute(
		"SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s",
		(table, column),
	)
	return bool(cr.fetchone())


def migrate(cr, version):
	"""Copia la configuración del shopping de los diarios a su sucursal DGI.

	Args:
		cr: cursor de base de datos.
		version (str): versión instalada antes de la actualización.
	"""
	if not _column_exists(cr, 'account_journal', 'codigoShopping'):
		return

	# SQL crudo: las columnas origen ya no son campos del ORM.
	cr.execute('''
		SELECT id FROM account_journal
		WHERE "integracionShopping" AND dgi_sucursal_id IS NULL
	''')
	for (journal_id,) in cr.fetchall():
		_logger.warning(
			"Diario %s tiene integración con Shopping pero no tiene Sucursal DGI: "
			"sus datos del shopping no se migran.", journal_id,
		)

	cr.execute('''
		SELECT DISTINCT ON (dgi_sucursal_id) dgi_sucursal_id, id
		FROM account_journal
		WHERE "integracionShopping" AND dgi_sucursal_id IS NOT NULL
		ORDER BY dgi_sucursal_id, COALESCE(secuencial_ventas, 0) DESC, id
	''')
	source_journal_by_sucursal = dict(cr.fetchall())

	assignments = ', '.join(
		'%s = journal.%s' % (target, source) for source, target in SHOPPING_COLUMNS.items()
	)
	for sucursal_id, journal_id in source_journal_by_sucursal.items():
		cr.execute(
			'''
			UPDATE dgi_sucursal sucursal SET %s
			FROM account_journal journal
			WHERE sucursal.id = %%s AND journal.id = %%s
			''' % assignments,
			(sucursal_id, journal_id),
		)
		cr.execute('''
			INSERT INTO dgi_sucursal_shopping_payment_rel (dgi_sucursal_id, payment_method_id)
			SELECT %s, payment_method_id
			FROM journal_shopping_payment_rel
			WHERE journal_id = %s
			ON CONFLICT DO NOTHING
		''', (sucursal_id, journal_id))
		_logger.info(
			"Sucursal DGI %s: datos del shopping migrados desde el diario %s.",
			sucursal_id, journal_id,
		)

	cr.execute('''
		SELECT dgi_sucursal_id, array_agg(id ORDER BY id), array_agg(secuencial_ventas ORDER BY id)
		FROM account_journal
		WHERE "integracionShopping" AND dgi_sucursal_id IS NOT NULL
		GROUP BY dgi_sucursal_id
		HAVING count(*) > 1
	''')
	for sucursal_id, journal_ids, sequences in cr.fetchall():
		_logger.warning(
			"Sucursal DGI %s: los diarios %s compartían contrato con secuenciales %s. "
			"Se tomó el mayor; confirmar con la Administración del shopping el próximo a enviar.",
			sucursal_id, journal_ids, sequences,
		)
