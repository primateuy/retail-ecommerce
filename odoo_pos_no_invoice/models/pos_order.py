from datetime import date as py_date
from datetime import datetime
import time

from odoo import _, models, api, fields
from odoo.tools import is_html_empty
import logging

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    """
    Extensión del modelo pos.order para manejar facturación sin descarga de PDF
    y asegurar que account_move esté disponible en el resultado.
    También proporciona métodos para obtener datos del CFE desde account_move
    para mostrarlos en el recibo.
    """
    _inherit = 'pos.order'

    def _generate_pos_order_invoice(self):
        """
        Genera la factura de la orden POS sin generar PDF

        Este método sobrescribe el método estándar para deshabilitar la generación
        de PDF durante la creación de la factura, lo cual es útil cuando se usa
        facturación electrónica que genera su propio PDF.

        Solo se aplica si la configuración 'download_invoice' del POS está en False.
        Si está en True, se mantiene el comportamiento estándar de Odoo.

        Returns:
            dict: Resultado de la generación de factura (puede ser un dict vacío
                  o un dict con información de la factura)
        """
        # Verificar si la configuración del POS permite descargar factura
        # Si download_invoice es True, usar comportamiento estándar
        if self.config_id.download_invoice:
            return super(PosOrder, self)._generate_pos_order_invoice()

        # Si download_invoice es False, deshabilitar generación de PDF
        ctx = dict(self.env.context)
        ctx['generate_pdf'] = False
        self = self.with_context(ctx)
        res = super(PosOrder, self)._generate_pos_order_invoice()
        return res

    @api.model
    def create_from_ui(self, orders, draft=False):
        """
        Crea órdenes desde la interfaz de usuario y asegura que account_move
        esté disponible en el resultado cuando la orden está facturada

        Este método sobrescribe el método estándar para asegurar que después
        de procesar las órdenes, si alguna está facturada, el campo account_move
        esté incluido en el resultado que se retorna al frontend.

        El problema que resuelve es que cuando se genera facturación electrónica,
        el proceso puede tomar tiempo y el campo account_move puede no estar
        disponible inmediatamente en el resultado serializado.

        Args:
            orders (list): Lista de órdenes a procesar
            draft (bool): Indica si las órdenes son borradores

        Returns:
            list: Lista de diccionarios con información de las órdenes procesadas,
                  incluyendo account_move si la orden está facturada
        """
        _logger.info(
            'create_from_ui llamado con %s órdenes, draft=%s',
            len(orders) if orders else 0,
            draft
        )

        # Procesar las órdenes normalmente
        result = super(PosOrder, self).create_from_ui(orders, draft)

        # IMPORTANTE: Siempre asegurar que account_move esté disponible en el resultado
        # cuando la orden está facturada, independientemente del valor de download_invoice.
        # Esto es necesario porque:
        # - Si download_invoice = True: el frontend necesita account_move para descargar la factura
        # - Si download_invoice = False: el frontend puede necesitar account_move para otras operaciones
        #
        # La diferencia está solo en la generación de PDF (manejada en _generate_pos_order_invoice)
        # y en el comportamiento del frontend (manejado en payment_screen.js)

        # Extraer referencias de las órdenes antes de procesarlas
        order_references = []
        if orders:
            for order_data in orders:
                if isinstance(order_data, dict) and 'data' in order_data:
                    order_ref = order_data['data'].get('name') or order_data['data'].get('pos_reference')
                    if order_ref:
                        order_references.append(order_ref)
                elif isinstance(order_data, dict) and 'name' in order_data:
                    order_references.append(order_data.get('name'))

        _logger.info('Referencias de órdenes a procesar: %s', order_references)

        _logger.info(
            'create_from_ui retornó resultado tipo %s con %s elementos',
            type(result).__name__,
            len(result) if isinstance(result, (list, tuple)) else 'N/A'
        )

        # Si no es borrador, buscar las órdenes procesadas y agregar account_move
        # Esto se hace SIEMPRE, independientemente de download_invoice, para asegurar
        # que el frontend tenga acceso a account_move cuando la orden está facturada
        if not draft:
            # Si el resultado está vacío, buscar las órdenes por referencia
            if not result or (isinstance(result, (list, tuple)) and len(result) == 0):
                _logger.info('Resultado vacío, buscando órdenes por referencia')
                for order_ref in order_references:
                    try:
                        # Buscar la orden por referencia
                        order = self.search([('pos_reference', '=', order_ref)], limit=1)
                        if not order:
                            # Intentar buscar por name si pos_reference no funciona
                            order = self.search([('name', '=', order_ref)], limit=1)

                        if order:
                            # Leer account_move directamente desde la BD
                            self.env.cr.execute(
                                "SELECT account_move FROM pos_order WHERE id = %s",
                                (order.id,)
                            )
                            account_move_result = self.env.cr.fetchone()

                            if account_move_result and account_move_result[0]:
                                account_move_id = account_move_result[0]

                                # Construir el resultado con account_move
                                if not result:
                                    result = []
                                result.append({
                                    'id': order.id,
                                    'account_move': account_move_id
                                })
                                _logger.info(
                                    '✓ Agregado account_move al resultado para orden %s (ID: %s): %s',
                                    order_ref,
                                    order.id,
                                    account_move_id
                                )
                            else:
                                _logger.info('Orden %s (ID: %s) no tiene account_move aún', order_ref, order.id)
                    except Exception as e:
                        _logger.warning(
                            'Error al buscar orden por referencia %s: %s',
                            order_ref,
                            str(e),
                            exc_info=True
                        )
            else:
                # Si el resultado tiene elementos, agregar account_move a cada uno
                if isinstance(result, (list, tuple)):
                    for idx, order_result in enumerate(result):
                        if isinstance(order_result, dict) and 'id' in order_result:
                            try:
                                order_id = order_result.get('id')
                                if order_id:
                                    # Leer account_move directamente desde la BD
                                    self.env.cr.execute(
                                        "SELECT account_move FROM pos_order WHERE id = %s",
                                        (order_id,)
                                    )
                                    account_move_result = self.env.cr.fetchone()

                                    if account_move_result and account_move_result[0]:
                                        account_move_id = account_move_result[0]

                                        if 'account_move' not in order_result or not order_result.get('account_move'):
                                            order_result['account_move'] = account_move_id
                                            _logger.info(
                                                '✓ Agregado account_move al resultado[%s] para orden ID %s: %s',
                                                idx,
                                                order_id,
                                                account_move_id
                                            )
                            except Exception as e:
                                _logger.warning(
                                    'Error al agregar account_move al resultado[%s]: %s',
                                    idx,
                                    str(e),
                                    exc_info=True
                                )

        _logger.info(
            'create_from_ui retornando resultado final: %s elementos',
            len(result) if isinstance(result, (list, tuple)) else 'N/A'
        )

        return result

    @api.model
    def get_cfe_data_from_invoice(self, ids, account_move_id):
        """
        Obtiene los datos del CFE directamente desde account_move (factura)

        Este método extrae la información del CFE desde account_move
        y la formatea para ser incluida en el recibo del POS.

        Args:
            ids (list): Lista de IDs de pos.order (no se usa, pero es requerido por @api.model)
            account_move_id (int): ID del account.move (factura)

        Returns:
            dict: Diccionario con los datos del CFE formateados para el recibo.
                  Retorna un diccionario vacío si no hay CFE disponible.
        """
        _logger.info('=== INICIO get_cfe_data_from_invoice ===')
        _logger.info('ids recibido: %s, account_move_id recibido: %s (tipo: %s)', ids, account_move_id,
                     type(account_move_id))

        if not account_move_id:
            _logger.warning('No se recibió account_move_id')
            return {}

        cfe_data = {}

        try:
            # Obtener la factura (account.move)
            invoice = self.env['account.move'].browse(account_move_id)
            if not invoice.exists():
                _logger.warning('Factura %s no existe', account_move_id)
                return {}

            # Invalidar cache y re-leer con sudo para asegurar datos actualizados y acceso completo.
            invoice.invalidate_recordset(
                ['cfe_serie_num', 'name', 'cfe_hash', 'cfe_url_qr', 'cfe_type', 'qr_img', 'cfe_cae_from', 'cfe_cae_to',
                 'cfe_cae_exp_date', 'cfe_cae_auth'])
            invoice = invoice.sudo().browse(account_move_id)

            _logger.info('Factura encontrada: ID=%s, name=%s', invoice.id, invoice.name)

            # Parsear serie y número desde cfe_serie_num o desde el nombre de la factura
            serie = ''
            numero = ''
            tipo = ''
            cfe_serie_num = ''

            # Intentar desde cfe_serie_num primero
            if hasattr(invoice, 'cfe_serie_num') and invoice.cfe_serie_num and str(
                    invoice.cfe_serie_num).strip() not in [False, '/', '']:
                _logger.info('Parseando cfe_serie_num: %s', invoice.cfe_serie_num)
                cfe_serie_num = str(invoice.cfe_serie_num).strip()
                parts = str(invoice.cfe_serie_num).split('-')
                if len(parts) >= 3:
                    tipo = parts[0].strip()
                    serie = parts[1].strip()
                    numero = parts[2].strip()
                    _logger.info('Parseado: tipo=%s, serie=%s, numero=%s', tipo, serie, numero)

            # Si no se pudo parsear desde cfe_serie_num, intentar desde el nombre
            if not serie and hasattr(invoice, 'name') and invoice.name and invoice.name.strip() not in ['/', '']:
                _logger.info('Intentando parsear desde invoice.name: %s', invoice.name)
                if '-' in invoice.name:
                    parts = invoice.name.split('-')
                    if len(parts) >= 3:
                        tipo = parts[0].strip()
                        serie = parts[1].strip()
                        numero = parts[2].strip()
                        cfe_serie_num = invoice.name.strip()
                        _logger.info('Parseado desde name: tipo=%s, serie=%s, numero=%s', tipo, serie, numero)

            # Si no hay tipo, intentar desde cfe_type
            if not tipo and hasattr(invoice, 'cfe_type') and invoice.cfe_type:
                tipo = str(invoice.cfe_type).strip()
                _logger.info('Tipo obtenido desde cfe_type: %s', tipo)

            # Validar que tengamos serie y número
            if not serie or not numero:
                _logger.info('Factura %s no tiene serie y número completos (serie="%s", numero="%s")', account_move_id,
                             serie, numero)
                return {}

            # Obtener el nombre del tipo de CFE
            tipo_nombre = ''
            if tipo:
                tipo_map = {
                    '101': 'eTicket',
                    '111': 'eTicket',
                    '112': 'eFactura',
                    '113': 'eFactura Exportación',
                    '181': 'eRemito',
                    '182': 'eResguardo',
                }
                tipo_nombre = tipo_map.get(tipo, f'CFE {tipo}')

            # Obtener RUT de la empresa
            ruc_emisor = ''
            if invoice.company_id and invoice.company_id.vat:
                ruc_emisor = invoice.company_id.vat

            # Obtener código de seguridad
            codigo_seguridad = ''
            if hasattr(invoice, 'cfe_hash') and invoice.cfe_hash:
                codigo_seguridad = invoice.cfe_hash

            # Obtener URL de verificación
            url_verificacion = ''
            if hasattr(invoice, 'cfe_url_text') and invoice.cfe_url_text:
                url_verificacion = invoice.cfe_url_text
            elif hasattr(invoice, 'cfe_url_qr') and invoice.cfe_url_qr:
                url_verificacion = invoice.cfe_url_qr

            # Obtener CAE
            cae_numero = ''
            if hasattr(invoice, 'cfe_cae_auth') and invoice.cfe_cae_auth:
                cae_numero = invoice.cfe_cae_auth

            # Obtener rangos CAE
            cae_rango_desde = ''
            cae_rango_hasta = ''
            if hasattr(invoice, 'cfe_cae_from') and invoice.cfe_cae_from:
                cae_rango_desde = str(invoice.cfe_cae_from)
            if hasattr(invoice, 'cfe_cae_to') and invoice.cfe_cae_to:
                cae_rango_hasta = str(invoice.cfe_cae_to)

            # Formatear fecha de vencimiento CAE
            fecha_vencimiento = ''
            if hasattr(invoice, 'cfe_cae_exp_date') and invoice.cfe_cae_exp_date:
                try:
                    if isinstance(invoice.cfe_cae_exp_date, str):
                        from datetime import datetime
                        fecha = datetime.strptime(invoice.cfe_cae_exp_date, '%Y-%m-%d')
                        fecha_vencimiento = fecha.strftime('%d/%m/%Y')
                    else:
                        fecha_vencimiento = invoice.cfe_cae_exp_date.strftime('%d/%m/%Y')
                except Exception:
                    fecha_vencimiento = str(invoice.cfe_cae_exp_date)

            # Obtener QR en base64
            qr_base64 = ''
            if hasattr(invoice, 'qr_img') and invoice.qr_img:
                qr_base64 = invoice.qr_img

            # Obtener moneda de la transacción
            moneda = invoice.currency_id.name if invoice.currency_id else ''

            # Obtener datos de sucursal y punto de emisión desde el diario de la factura
            sucursal_nombre = ''
            sucursal_direccion = ''
            sucursal_ciudad = ''
            punto_emision_nombre = ''
            journal = invoice.journal_id
            if journal:
                if hasattr(journal, 'dgi_sucursal_id') and journal.dgi_sucursal_id:
                    sucursal = journal.dgi_sucursal_id
                    sucursal_nombre = sucursal.name or ''
                    if hasattr(sucursal, 'direccion_partner_id') and sucursal.direccion_partner_id:
                        addr = sucursal.direccion_partner_id
                        sucursal_direccion = addr.street or ''
                        sucursal_ciudad = addr.city or ''
                if hasattr(journal, 'punto_emision_id') and journal.punto_emision_id:
                    punto_emision_nombre = journal.punto_emision_id.name or ''

            # Construir objeto con datos del CFE
            cfe_data = {
                'tipo': tipo_nombre,
                'tipo_codigo': tipo,
                'serie': serie,
                'numero': numero,
                'cfe_serie_num': cfe_serie_num or f'{tipo}-{serie}-{numero}' if (tipo and serie and numero) else '',
                'ruc_emisor': ruc_emisor,
                'codigo_seguridad': codigo_seguridad,
                'url_verificacion': url_verificacion,
                'cae_numero': cae_numero,
                'cae_rango_desde': cae_rango_desde,
                'cae_rango_hasta': cae_rango_hasta,
                'cae_fecha_vencimiento': fecha_vencimiento,
                'qr_base64': qr_base64,
                'moneda': moneda,
                'sucursal_nombre': sucursal_nombre,
                'sucursal_direccion': sucursal_direccion,
                'sucursal_ciudad': sucursal_ciudad,
                'punto_emision': punto_emision_nombre,
            }

            _logger.info(
                '✓ Datos CFE obtenidos desde factura %s: tipo=%s, serie=%s, numero=%s | '
                'journal_id=%s dgi_sucursal_id=%s sucursal_nombre=%r sucursal_direccion=%r sucursal_ciudad=%r',
                account_move_id, tipo_nombre, serie, numero,
                invoice.journal_id.id if invoice.journal_id else None,
                invoice.journal_id.dgi_sucursal_id.id if invoice.journal_id and invoice.journal_id.dgi_sucursal_id else None,
                sucursal_nombre, sucursal_direccion, sucursal_ciudad,
            )

        except Exception as e:
            _logger.error('Error al obtener datos CFE desde factura %s: %s', account_move_id, str(e), exc_info=True)
            return {}

        return cfe_data

    def _normalize_payment_name(self, name):
        """Normaliza el nombre del medio de pago.
        Si contiene 'efectivo' (case insensitive), devuelve 'Efectivo'.
        """
        if name and 'efectivo' in name.lower():
            return 'Efectivo'
        return name or ''

    @api.model
    def get_receipt_data_from_invoice_or_order(self, ids, account_move_id, order_reference, order_id=None):
        """
        Retorna los datos del recibo tomando como prioridad la factura generada
        y, si no existe, la orden del POS.

        Este método centraliza la construcción de líneas, totales, impuestos,
        información legal y adenda para asegurar consistencia con la factura.
        """
        # Nota: `ids` es parte de la firma estándar de @api.model y no se usa aquí.
        # Inicializar la estructura base de respuesta para el recibo.
        receipt_data = {
            'source': 'none',
            'account_move_id': False,
            'order_id': False,
            'orderlines': [],
            'paymentlines': [],
            'amount_total': 0.0,
            'amount_tax': 0.0,
            'total_without_tax': 0.0,
            'total_received': 0.0,
            'currency_name': '',
            'receipt_logo': False,
            'tax_details': [],
            'legal_data': {
                'purchase_condition': '',
                'ticket_number': '',
                'date': '',
                'document_type': '',
                'customer_name': '',
                'branch_name': '',
            },
            'adenda_data': {
                'cashier': '',
                'seller': '',
                'points_policy': '',
                'return_policy': '',
            },
        }

        # Normalizar parámetros de entrada para evitar errores en búsquedas.
        normalized_reference = (order_reference or '').strip()
        normalized_account_move_id = int(account_move_id) if account_move_id else False
        normalized_order_id = int(order_id) if order_id else False

        # Buscar la orden del POS por ID si está disponible (más confiable que la referencia).
        pos_order = self.env['pos.order']
        if normalized_order_id:
            pos_order = self.browse(normalized_order_id).sudo()
            if not pos_order.exists():
                pos_order = self.env['pos.order']

        # Si no se encontró por ID, buscar la orden por referencia para usar como respaldo.
        if not pos_order and normalized_reference:
            pos_order = self.search(
                ['|', ('pos_reference', '=', normalized_reference), ('name', '=', normalized_reference)],
                limit=1,
                order='id desc'
            )

        # Asignar la orden encontrada a la respuesta para trazabilidad.
        if pos_order:
            receipt_data['order_id'] = pos_order.id

        # Usar la factura de la orden si no se recibió account_move_id explícito.
        if not normalized_account_move_id and pos_order:
            for _attempt in range(20):
                pos_order.invalidate_recordset(['account_move'])
                pos_order = self.browse(pos_order.id).sudo()
                if pos_order.account_move:
                    normalized_account_move_id = pos_order.account_move.id
                    break
                time.sleep(1)
        # Preparar la factura en caso de existir para construir el recibo.
        invoice = self.env['account.move']
        if normalized_account_move_id:
            invoice = self.env['account.move'].browse(normalized_account_move_id)
            if not invoice.exists():
                invoice = self.env['account.move']
                normalized_account_move_id = False
        invoice = invoice.sudo() if invoice else invoice

        # Determinar la condición de compra priorizando la factura.
        purchase_condition = ''
        if invoice and invoice.invoice_payment_term_id:
            purchase_condition = invoice.invoice_payment_term_id.name or ''
        elif pos_order and pos_order.payment_ids:
            purchase_condition = pos_order.payment_ids[0].payment_method_id.name or ''
        else:
            purchase_condition = 'Contado'

        # Determinar el número de ticket usando la orden y la factura como fallback.
        ticket_number = ''
        if pos_order and (pos_order.pos_reference or pos_order.name):
            ticket_number = pos_order.pos_reference or pos_order.name
        elif invoice and invoice.name:
            ticket_number = invoice.name

        # Determinar la fecha del ticket en formato dd/mm/yyyy.
        ticket_date = ''
        raw_date = False
        if invoice and (invoice.invoice_date or invoice.date):
            raw_date = invoice.invoice_date or invoice.date
        elif pos_order and pos_order.date_order:
            raw_date = pos_order.date_order
        if raw_date:
            if isinstance(raw_date, datetime):
                ticket_date = raw_date.strftime('%d/%m/%Y')
            elif isinstance(raw_date, py_date):
                ticket_date = raw_date.strftime('%d/%m/%Y')
            else:
                try:
                    parsed = fields.Date.from_string(raw_date)
                    ticket_date = parsed.strftime('%d/%m/%Y')
                except Exception:
                    ticket_date = str(raw_date)

        # Determinar el tipo de documento desde la factura si existe.
        document_type = ''
        if invoice and 'cfe_type' in invoice._fields and invoice.cfe_type:
            document_type = str(invoice.cfe_type)
        elif invoice and invoice.move_type:
            document_type = invoice.move_type

        # Determinar el cliente desde la factura, si no, desde la orden.
        customer_name = ''
        if invoice and invoice.partner_id:
            customer_name = invoice.partner_id.name or ''
        elif pos_order and pos_order.partner_id:
            customer_name = pos_order.partner_id.name or ''
        if not customer_name:
            customer_name = 'Consumidor final'

        # Determinar la sucursal a partir de la configuración del POS.
        branch_name = ''
        if pos_order and pos_order.config_id:
            branch_name = pos_order.config_id.name or ''

        # Logo de rutina de impresión desde la compañía.
        company = (invoice.company_id if invoice else False) or (pos_order.company_id if pos_order else False)
        if company and hasattr(company, 'pos_receipt_logo') and company.pos_receipt_logo:
            receipt_data['receipt_logo'] = company.pos_receipt_logo.decode('utf-8') if isinstance(
                company.pos_receipt_logo, bytes) else company.pos_receipt_logo

        # Moneda de la transacción.
        if invoice and invoice.currency_id:
            receipt_data['currency_name'] = invoice.currency_id.name or ''
        elif pos_order and hasattr(pos_order, 'currency_id') and pos_order.currency_id:
            receipt_data['currency_name'] = pos_order.currency_id.name or ''

        # Líneas de pago normalizadas desde la orden POS (todas, no solo la primera).
        if pos_order and pos_order.payment_ids:
            total_received = 0.0
            paymentlines = []
            for payment in pos_order.payment_ids:
                pname = self._normalize_payment_name(payment.payment_method_id.name or '')
                pamount = payment.amount or 0.0
                total_received += pamount
                paymentlines.append({'name': pname, 'amount': pamount})
            receipt_data['paymentlines'] = paymentlines
            receipt_data['total_received'] = total_received

        # Asignar información legal al recibo.
        receipt_data['legal_data'].update({
            'purchase_condition': purchase_condition,
            'ticket_number': ticket_number,
            'date': ticket_date,
            'document_type': document_type,
            'customer_name': customer_name,
            'branch_name': branch_name,
        })

        # Construir datos de adenda desde la orden del POS.
        # Vendedor: si la config del POS tiene "Allow Salesperson", usar el salesperson de la 1ª línea;
        # si no, mantener el valor actual (employee_id o vacío).
        if pos_order:
            seller = ''
            config = pos_order.config_id
            allow_salesperson = bool(config and getattr(config, 'allow_salesperson', False))
            if allow_salesperson and pos_order.lines:
                first_line = pos_order.lines[0]
                if getattr(first_line, 'user_id', None) and first_line.user_id:
                    seller = first_line.user_id.name or ''
            if not seller:
                seller = (
                    pos_order.employee_id.name
                    if hasattr(pos_order, 'employee_id') and pos_order.employee_id
                    else ''
                )
            receipt_data['adenda_data'].update({
                'cashier': (
                    pos_order.employee_id.name
                    if hasattr(pos_order, 'employee_id') and pos_order.employee_id
                    else pos_order.user_id.name if pos_order.user_id else ''
                ),
                'seller': seller,
                'points_policy': pos_order.config_id.pos_points_policy if pos_order.config_id else '',
            })

        # Aplicar el comportamiento estándar de Odoo para términos y condiciones.
        use_invoice_terms = self.env['ir.config_parameter'].sudo().get_param('account.use_invoice_terms')
        if use_invoice_terms:
            company = invoice.company_id if invoice else (pos_order.company_id if pos_order else False)
            if company:
                if company.terms_type != 'html':
                    if not is_html_empty(company.invoice_terms or ''):
                        receipt_data['adenda_data']['return_policy'] = company.invoice_terms
                else:
                    baseurl = company.get_base_url() + '/terms'
                    receipt_data['adenda_data']['return_policy'] = _('Terms & Conditions: %s', baseurl)

        # Construir líneas y totales desde la factura si está disponible.
        if invoice:
            receipt_data['source'] = 'invoice'
            receipt_data['account_move_id'] = invoice.id
            # Esperar a que la factura tenga líneas disponibles (incluye descuentos).
            expected_line_count = 0
            if pos_order:
                expected_line_count = len(pos_order.lines)

            invoice_lines = invoice.invoice_line_ids
            for _attempt in range(20):
                if invoice_lines and (not expected_line_count or len(invoice_lines) >= expected_line_count):
                    break
                time.sleep(1)
                invoice.invalidate_recordset(['invoice_line_ids', 'amount_total', 'amount_tax', 'amount_untaxed'])
                invoice = self.env['account.move'].browse(invoice.id).sudo()
                invoice_lines = invoice.invoice_line_ids

            if not invoice_lines:
                fallback_lines = invoice.line_ids.filtered(
                    lambda l: not l.display_type and not l.exclude_from_invoice_tab
                )
                if fallback_lines:
                    invoice_lines = fallback_lines

            receipt_data['amount_total'] = invoice.amount_total
            receipt_data['amount_tax'] = invoice.amount_tax
            receipt_data['total_without_tax'] = invoice.amount_untaxed

            # Construir líneas del recibo a partir de las líneas de factura.
            for line in invoice_lines:
                is_note = line.display_type == 'note'
                is_combo = False
                if not is_note and line.tax_ids:
                    for tax in line.tax_ids:
                        if 'entrega gratuita' in (tax.name or '').lower():
                            is_combo = True
                            break
                receipt_data['orderlines'].append({
                    'productName': line.name or (line.product_id.display_name if line.product_id else ''),
                    'qty': line.quantity,
                    'unitPrice': line.price_unit,
                    'price': line.price_total,
                    'discount': line.discount or 0.0,
                    'customerNote': '',
                    'is_note': is_note,
                    'is_combo': is_combo,
                })

            # Las líneas de pago ya fueron construidas desde pos_order arriba.
            # Si no había orden POS, usar el total de la factura como fallback.
            if not receipt_data['paymentlines']:
                payment_name = purchase_condition or 'Contado'
                receipt_data['paymentlines'] = [{'name': payment_name, 'amount': invoice.amount_total}]
                receipt_data['total_received'] = invoice.amount_total

            # Construir detalle de impuestos desde tax_totals si está disponible.
            tax_totals = invoice.tax_totals or {}
            groups_by_subtotal = tax_totals.get('groups_by_subtotal', {})
            for group_list in groups_by_subtotal.values():
                for group in group_list:
                    receipt_data['tax_details'].append({
                        'tax_group_name': group.get('tax_group_name') or '',
                        'tax_group_rate': group.get('tax_group_rate'),
                        'tax_group_base_amount': group.get('tax_group_base_amount') or 0.0,
                        'tax_group_amount': group.get('tax_group_amount') or 0.0,
                    })

        # Si no hay factura, construir líneas y totales desde la orden del POS.
        elif pos_order:
            receipt_data['source'] = 'order'
            receipt_data['amount_total'] = pos_order.amount_total
            receipt_data['amount_tax'] = pos_order.amount_tax
            receipt_data['total_without_tax'] = pos_order.amount_untaxed

            # Construir líneas del recibo a partir de las líneas de la orden.
            for line in pos_order.lines:
                is_note = getattr(line, 'display_type', '') == 'note'
                is_combo = False
                if not is_note and hasattr(line, 'tax_ids') and line.tax_ids:
                    for tax in line.tax_ids:
                        if 'entrega gratuita' in (tax.name or '').lower():
                            is_combo = True
                            break
                receipt_data['orderlines'].append({
                    'productName': line.name or (line.product_id.display_name if line.product_id else ''),
                    'qty': line.qty,
                    'unitPrice': line.price_unit,
                    'price': line.price_subtotal_incl if hasattr(line, 'price_subtotal_incl') else line.price_subtotal,
                    'discount': line.discount or 0.0,
                    'customerNote': line.note if hasattr(line, 'note') and line.note else '',
                    'is_note': is_note,
                    'is_combo': is_combo,
                })

            # Intentar construir detalle de impuestos desde la orden usando tax_totals si existe.
            if hasattr(pos_order, 'tax_totals') and pos_order.tax_totals:
                groups_by_subtotal = pos_order.tax_totals.get('groups_by_subtotal', {})
                for group_list in groups_by_subtotal.values():
                    for group in group_list:
                        receipt_data['tax_details'].append({
                            'tax_group_name': group.get('tax_group_name') or '',
                            'tax_group_rate': group.get('tax_group_rate'),
                            'tax_group_base_amount': group.get('tax_group_base_amount') or 0.0,
                            'tax_group_amount': group.get('tax_group_amount') or 0.0,
                        })

        return receipt_data