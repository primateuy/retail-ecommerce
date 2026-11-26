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
		(A4 o rollo según el punto de emisión), reutilizando el PDF que la localización
		ya guardó al firmar. Si el CFE no fue emitido, devuelve la descarga estándar de
		Odoo.

		Args:
			target (str): Destino de la acción URL (``download``, ``_blank``, ...).

		Returns:
			dict|bool: Acción ``ir.actions.act_url``, o False si el CFE fue emitido pero
				Uruware no devolvió el PDF.

		Efectos colaterales:
			Si la factura todavía no tiene el PDF, lo pide a Uruware y guarda el adjunto en
			``pos_cfe_pdf_attachment_id``.
		"""
		self.ensure_one()
		if not self.cfe_emitido:
			return self.action_invoice_download_pdf(target)
		attachment = self._get_pos_cfe_pdf_attachment()
		if not attachment:
			# Con FE activa la descarga estándar también pide el PDF a Uruware y, si Uruware
			# no responde, termina en error de servidor y deja al PdV en la pantalla de pago
			# con la venta ya facturada. El PdV avisa y la factura se reimprime desde Órdenes.
			return False
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

		Antes de llamar a Uruware busca el PDF que ``l10n_uy_einvoice_uruware`` ya guarda
		al firmar el CFE, así no se pide dos veces ni se duplica el adjunto.

		Returns:
			ir.attachment: El adjunto, o un recordset vacío si Uruware no lo devolvió.
		"""
		self.ensure_one()
		if self.pos_cfe_pdf_attachment_id.exists():
			return self.pos_cfe_pdf_attachment_id
		attachment = self._find_uruware_pdf_attachment()
		if attachment:
			self.sudo().pos_cfe_pdf_attachment_id = attachment
			return attachment
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

	def _find_uruware_pdf_attachment(self):
		"""Busca el PDF del CFE que guardó ``obtener_pdf`` de la localización.

		El nombre del adjunto depende del formato del punto de emisión (A4, rollo
		estándar, rollo o rollo alternativo).

		Returns:
			ir.attachment: El adjunto más reciente, o un recordset vacío.
		"""
		names = [
			self.name,
			f'{self.name}_rollo.pdf',
			f'Rollo_CFE_{self.name}.pdf',
			f'Rollo_Alt_CFE_{self.name}.pdf',
		]
		# sudo: el cajero del PdV puede no ver los adjuntos que la firma creó con sudo.
		return self.env['ir.attachment'].sudo().search([
			('res_model', '=', self._name),
			('res_id', '=', self.id),
			('mimetype', '=', 'application/pdf'),
			('name', 'in', names),
		], order='id desc', limit=1)
