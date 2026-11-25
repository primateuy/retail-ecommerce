import logging
import re
from urllib.parse import urlsplit

from odoo import fields, models

_logger = logging.getLogger(__name__)

ATTACHMENT_URL_PATTERN = re.compile(r'^/web/content/(\d+)')


class AccountMove(models.Model):
	"""Descarga del CFE de Uruware desde el Punto de Venta."""

	_inherit = 'account.move'

	pos_cfe_pdf_attachment_id = fields.Many2one(
		comodel_name='ir.attachment',
		string="PDF del CFE (PdV)",
		copy=False,
		readonly=True,
	)

	def action_pos_download_cfe_pdf(self, target='download'):
		"""Devuelve la acción para descargar la factura desde el PdV.

		Si el CFE fue emitido, descarga su representación impresa de Uruware
		(A4 o rollo según el punto de emisión). La primera vez la pide con
		``obtener_pdf`` y guarda el adjunto; las siguientes reutiliza ese adjunto. Si el
		CFE no fue emitido, o Uruware falla, devuelve la descarga estándar de Odoo para
		que el cajero no se quede sin comprobante.

		Args:
			target (str): Destino de la acción URL (``download``, ``_blank``, ...).

		Returns:
			dict: Acción ``ir.actions.act_url``.

		Efectos colaterales:
			La primera descarga crea un ``ir.attachment`` con el PDF en la factura y lo
			guarda en ``pos_cfe_pdf_attachment_id``.
		"""
		self.ensure_one()
		if not self.cfe_emitido:
			return self.action_invoice_download_pdf(target)
		# Cada llamada a obtener_pdf crea un adjunto nuevo; los duplicados rompen a quien
		# después busca "el" adjunto de la factura (send_mail_invoice de pos_invoice_auto_check).
		attachment = self._get_pos_cfe_pdf_attachment()
		if not attachment:
			return self.action_invoice_download_pdf(target)
		return {
			'type': 'ir.actions.act_url',
			'url': f'/web/content/{attachment.id}?download=true',
			'target': target,
		}

	def get_pos_cfe_pdf_url(self):
		"""URL para mostrar o imprimir en el PdV el PDF del CFE de Uruware.

		Se usa en el panel del recibo y en «Imprimir recibo completo»; a diferencia de la
		descarga, el PDF se sirve en línea para que el navegador lo muestre o lo imprima.

		Returns:
			str|bool: ``/web/content/<id>`` del adjunto, o False si el CFE no fue emitido
				o Uruware no devolvió el PDF (el PdV usa entonces el recibo de Odoo).

		Efectos colaterales:
			La primera vez pide el PDF a Uruware y lo guarda como adjunto de la factura.
		"""
		self.ensure_one()
		if not self.cfe_emitido:
			return False
		attachment = self._get_pos_cfe_pdf_attachment()
		return f'/web/content/{attachment.id}' if attachment else False

	def _get_pos_cfe_pdf_attachment(self):
		"""Devuelve el adjunto con el PDF del CFE, pidiéndolo a Uruware si no existe.

		Returns:
			ir.attachment: El adjunto, o un recordset vacío si Uruware no lo devolvió.
		"""
		self.ensure_one()
		if self.pos_cfe_pdf_attachment_id.exists():
			return self.pos_cfe_pdf_attachment_id
		attachment = self.env['ir.attachment']
		try:
			action = self.obtener_pdf()
		except Exception:
			# Un error de Uruware no debe dejar la venta sin comprobante impreso.
			_logger.exception("No se pudo obtener el PDF del CFE %s desde Uruware", self.name)
			return attachment
		url = action.get('url') if isinstance(action, dict) else False
		# obtener_pdf arma la URL con web.base.url; el id del adjunto está en la ruta.
		match = url and ATTACHMENT_URL_PATTERN.match(urlsplit(url).path)
		if match:
			attachment = attachment.browse(int(match.group(1))).exists()
		if attachment:
			# El cajero del PdV puede no tener permiso de escritura sobre facturas; el adjunto
			# ya lo creó obtener_pdf con sudo y sólo se guarda la referencia.
			self.sudo().pos_cfe_pdf_attachment_id = attachment
		return attachment
