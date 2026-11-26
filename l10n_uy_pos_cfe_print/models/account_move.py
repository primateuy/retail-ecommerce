import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)

# Nombres con los que obtener_pdf de l10n_uy_einvoice_uruware guarda el PDF del CFE, según
# el formato del punto de emisión: A4, rollo estándar, rollo y rollo alternativo.
CFE_PDF_NAME_PATTERNS = ('{}', '{}_rollo.pdf', 'Rollo_CFE_{}.pdf', 'Rollo_Alt_CFE_{}.pdf')


class AccountMove(models.Model):
	"""PDF del CFE de Uruware para descargar, mostrar e imprimir desde el Punto de Venta."""

	_inherit = 'account.move'

	pos_cfe_pdf_attachment_id = fields.Many2one(
		comodel_name='ir.attachment',
		string="PDF del CFE (PdV)",
		copy=False,
		readonly=True,
	)

	def get_pos_cfe_pdf(self):
		"""Datos del PDF del CFE para el PdV.

		Una sola llamada sirve a la descarga, al panel del recibo y a la impresión: la URL
		se sirve en línea y el PdV le agrega ``download=true`` para descargarla.

		Returns:
			dict: ``cfe_emitido`` (bool) y ``url`` (str con ``access_token``, o False si el
				CFE no fue emitido o Uruware no devolvió el PDF).

		Efectos colaterales:
			Si la factura todavía no tiene el PDF, lo pide a Uruware y guarda la referencia
			en ``pos_cfe_pdf_attachment_id``.
		"""
		self.ensure_one()
		if not self.cfe_emitido:
			return {'cfe_emitido': False, 'url': False}
		attachment = self._get_pos_cfe_pdf_attachment()
		if not attachment:
			return {'cfe_emitido': True, 'url': False}
		# El token evita depender de los permisos del cajero sobre el adjunto, que
		# pos_invoice_auto_check reasigna a la plantilla de mail al enviarlo.
		access_token = attachment.generate_access_token()[0]
		return {
			'cfe_emitido': True,
			'url': f'/web/content/{attachment.id}?access_token={access_token}',
		}

	def _get_pos_cfe_pdf_attachment(self):
		"""Devuelve el adjunto con el PDF del CFE, pidiéndolo a Uruware sólo si hace falta.

		Orden: la referencia ya guardada, el PDF que la localización guarda al firmar y,
		por último, ``obtener_pdf``.

		Returns:
			ir.attachment: El adjunto (con sudo), o vacío si Uruware no lo devolvió.
		"""
		self.ensure_one()
		# sudo: el cajero del PdV puede no ver ni escribir los adjuntos de la factura, que
		# la firma crea con sudo.
		attachment = self.pos_cfe_pdf_attachment_id.sudo().exists()
		if attachment:
			return attachment
		attachment = self._find_uruware_pdf_attachment()
		if not attachment:
			try:
				self.obtener_pdf()
			except Exception as error:
				# Uruware caído o sin respuesta: el PdV avisa y la venta sigue.
				_logger.warning(
					"No se pudo obtener el PDF del CFE %s desde Uruware: %s", self.name, error
				)
				return attachment
			attachment = self._find_uruware_pdf_attachment()
		if attachment:
			self.sudo().pos_cfe_pdf_attachment_id = attachment
		return attachment

	def _find_uruware_pdf_attachment(self):
		"""Busca el PDF del CFE que guardó ``obtener_pdf`` de la localización.

		Returns:
			ir.attachment: El más reciente (con sudo), o un recordset vacío.
		"""
		return self.env['ir.attachment'].sudo().search([
			('res_model', '=', self._name),
			('res_id', '=', self.id),
			('mimetype', '=', 'application/pdf'),
			('name', 'in', [pattern.format(self.name) for pattern in CFE_PDF_NAME_PATTERNS]),
		], order='id desc', limit=1)
