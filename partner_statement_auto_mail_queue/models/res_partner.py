import json
import base64
import logging

from datetime import timedelta, date
from odoo import models, fields, api
from dateutil.relativedelta import relativedelta

_logger = logging.getLogger('ENVIO REPORTES')


class ResPartner(models.Model):
    _inherit = 'res.partner'

    enviar_estado_cuenta = fields.Boolean('Enviar Estado de Cuenta', default=False)
    planilla_estado_cuenta_id = fields.Many2one('mail.template', 'Planilla Estado de Cuenta')

    enviar_estado_pendiente = fields.Boolean('Enviar Estado de Pendientes', default=False)
    planilla_estado_pendiente_id = fields.Many2one('mail.template', 'Planilla Estado Pendiente')

    email_alternativo = fields.Char('Email alternativo')

    statement_defaults = fields.Text('Statement defaults')
    outstanding_defaults = fields.Text('Outstanding defaults')

    numero_veces = fields.Integer('Ejecutar cada', default=1)
    periodo = fields.Selection([
        ('manually', 'Manual'),
        ('daily', 'Diario'),
        ('weekly', 'Semanal'),
        ('monthly', 'Mensual')
    ], 'Periodo', default='monthly')
    proximo_envio = fields.Date('Próximo envío')

    # Campos de control
    ultimo_envio = fields.Datetime('Último envío')

    only_company_ids = fields.Many2many('res.company', string='Solo enviar en compañías')

    def get_base_config_json(self):
        self.ensure_one()
        return {
            "show_aging_buckets": False,
            "filter_non_due_partners": True,
            "account_type": 'asset_receivable',
            "aging_type": 'months',
            "filter_negative_balances": True,
        }

    @api.onchange('enviar_estado_cuenta', 'enviar_estado_pendiente')
    def activar_jsons(self):
        for rec in self:
            if rec.enviar_estado_cuenta and not rec.statement_defaults:
                rec.statement_defaults = json.dumps(rec.get_base_config_json(), indent=4)

            if rec.enviar_estado_pendiente and not rec.outstanding_defaults:
                rec.outstanding_defaults = json.dumps(rec.get_base_config_json(), indent=4)

            if rec.enviar_estado_cuenta:
                rec.planilla_estado_cuenta_id = self.env.ref('partner_statement_auto_mail_queue.email_template_reporte_estados_cuenta', raise_if_not_found=False) or False

            if rec.enviar_estado_pendiente:
                rec.planilla_estado_pendiente_id = self.env.ref('partner_statement_auto_mail_queue.email_template_reporte_estados_pendiente', raise_if_not_found=False) or False

    def generar_pdf_estado_cuenta(self, company_id):
        self.ensure_one()
        data = self.get_data_estado_cuenta()
        data['company_id'] = company_id.id
        return self.generar_pdf('estado_cuenta.pdf', 'partner_statement.activity_statement', self, data)

    def get_data_estado_cuenta(self):
        self.ensure_one()
        if self.statement_defaults:
            base_data = json.loads(self.statement_defaults)
        else:
            base_data = self.get_base_config_json()
        base_data.update({
            "date_start": fields.Date.today() - timedelta(days=30),
            "date_end": fields.Date().today(),
            "is_activity": True,
            "partner_ids": [self.id],
            "excluded_accounts_ids": [],
            "show_only_overdue": False,
        })
        return base_data

    def generar_pdf_estado_pendientes(self, company_id):
        self.ensure_one()
        data = self.get_data_estado_pendientes()
        data['company_id'] = company_id.id
        return self.generar_pdf('estado_pendientes.pdf', 'partner_statement.outstanding_statement', self, data)

    def get_data_estado_pendientes(self):
        self.ensure_one()
        if self.outstanding_defaults:
            base_data = json.loads(self.outstanding_defaults)
        else:
            base_data = self.get_base_config_json()
        base_data.update({
            "date_end": fields.Date().today(),
            "is_outstanding": True,
            "partner_ids": [self.id],
            "excluded_accounts_ids": [],
            "show_only_overdue": False,
        })
        return base_data

    def generar_pdf(self, nombre, reporte_name, partner_id, data):
        self.ensure_one()
        pdf_data, _ = self.env["ir.actions.report"]._render_qweb_pdf(reporte_name, res_ids=partner_id, data=data)
        return self.env['ir.attachment'].create({
            'name': nombre,
            'datas': base64.b64encode(pdf_data),
            'type': 'binary',
            'mimetype': 'application/pdf',
        })

    def enviar_correo(self, company_id, template_id):
        for rec in self:
            _logger.info('ENVIAR CORREO %s PARTNER %s', template_id, rec)

            try:
                with self.env.cr.savepoint():
                    record_values = template_id._generate_template(
                        rec.ids,
                        ['attachment_ids',
                         'body_html',
                         'email_cc',
                         'email_from',
                         'email_to',
                         'mail_server_id',
                         'model',
                         'partner_to',
                         'reply_to',
                         'report_template_ids',
                         'res_id',
                         'scheduled_date',
                         'subject',
                         ]
                    )

                    if len(record_values) > 0 and rec.id in record_values:
                        mail_values = record_values[rec.id]
                        mail_values.pop('attachments', False)
                        mail_values['body'] = mail_values.get('body_html')
                        mail_values['auto_delete'] = False
                        mail_values['email_from'] = company_id.email_formatted
                        mail_values['recipient_ids'] = [(6, 0, [rec.id])]

                        mail_id = self.env['mail.mail'].sudo().create(mail_values)

                        if rec.enviar_estado_cuenta:
                            attachemnts_ids = rec.generar_pdf_estado_cuenta(company_id)
                        else:
                            attachemnts_ids = rec.generar_pdf_estado_pendientes(company_id)

                        mail_id.write({
                            'attachment_ids': [(6, 0, attachemnts_ids.ids)],
                        })

            except Exception as e:
                _logger.info('Error ENVIANDO REPORTE', e)
                msg = f"Error enviando reporte: {str(e)}"
                rec.message_post(body=msg)

            rec.write({
                'ultimo_envio': fields.Datetime.now(),
            })

    def _tiene_deuda_vencida(self, company_id):
        """Indica si el cliente tiene deuda vencida en la compañía dada.

        Usa el mismo criterio que el aviso de account_invoice_overdue_warn
        que se muestra en la ficha del cliente ("Este cliente tiene N
        factura(s) vencida(s)..."), visible cuando overdue_invoice_count != 0.
        """
        self.ensure_one()
        count, _amount = self._prepare_overdue_invoice_count_amount(company_id.id)
        return count > 0

    def avanzar_proximo_envio(self):
        self.ensure_one()
        next_update = False

        if self.periodo == 'daily':
            next_update = relativedelta(days=+self.numero_veces)

        if self.periodo == 'weekly':
            next_update = relativedelta(weeks=+self.numero_veces)

        if self.periodo == 'monthly':
            next_update = relativedelta(months=+self.numero_veces)

        if not next_update:
            self.write({'proximo_envio': False})
        else:
            self.write({'proximo_envio': date.today() + next_update})

    @api.model
    def cron_enviar_reportes(self):
        today = fields.Date.today()

        partner_ids = self.env['res.partner'].search([
            ('enviar_estado_cuenta', '=', True),
            ('proximo_envio', '<=', today),
            ('periodo', '!=', 'manually'),
        ])

        partner_ids += self.env['res.partner'].search([
            ('enviar_estado_pendiente', '=', True),
            ('proximo_envio', '<=', today),
            ('periodo', '!=', 'manually'),
            ('id', 'not in', partner_ids.ids),
        ])

        for company_id in self.env['res.company'].search([]):
            filter_partner_ids = partner_ids.filtered(lambda l: (company_id in l.only_company_ids) or len(l.only_company_ids) == 0)

            for partner_id in filter_partner_ids:
                # No enviar a clientes sin deuda vencida (mismo indicador que
                # el aviso mostrado en la ficha del cliente).
                if not partner_id._tiene_deuda_vencida(company_id):
                    _logger.info(
                        'OMITIDO PARTNER %s en compañía %s: sin deuda vencida',
                        partner_id.id, company_id.name,
                    )
                    partner_id.avanzar_proximo_envio()
                    continue

                if partner_id.enviar_estado_cuenta:
                    partner_id.enviar_correo(company_id, partner_id.planilla_estado_cuenta_id)

                if partner_id.enviar_estado_pendiente:
                    partner_id.enviar_correo(company_id, partner_id.planilla_estado_pendiente_id)

                partner_id.avanzar_proximo_envio()
