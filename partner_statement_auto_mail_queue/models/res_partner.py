import json
import base64
import logging

from datetime import timedelta
from odoo import models, fields, api

_logger = logging.getLogger('ENVIO REPORTES')


class ResPartner(models.Model):
    _inherit = 'res.partner'

    enviar_estado_cuenta = fields.Boolean('Enviar Estado de Cuenta', default=False)
    enviar_estado_pendiente = fields.Boolean('Enviar Estado de Pendientes', default=False)
    email_alternativo = fields.Char('Email alternativo')

    statement_defaults = fields.Text('Statement defaults')
    outstanding_defaults = fields.Text('Outstanding defaults')

    # Campos de control
    ultimo_envio = fields.Datetime('Último envío')
    proximo_envio = fields.Datetime('Próximo envío', compute='compute_proximo_envio')

    only_company_ids = fields.Many2many('res.company', string='Solo enviar en compañías')

    def compute_proximo_envio(self):
        for rec in self:
            cron_id = self.env.ref('partner_statement_auto_mail_queue.ir_cron_send_report')
            rec.proximo_envio = cron_id.nextcall

    def get_base_config_json(self):
        self.ensure_one()
        return {
            "show_aging_buckets": True,
            "filter_non_due_partners": True,
            "account_type": 'asset_receivable',
            "aging_type": 'days',
            "filter_negative_balances": True,
        }

    @api.onchange('enviar_estado_cuenta', 'enviar_estado_pendiente')
    def activar_jsons(self):
        for rec in self:
            if rec.enviar_estado_cuenta and not rec.statement_defaults:
                rec.statement_defaults = json.dumps(rec.get_base_config_json(), indent=4)

            if rec.enviar_estado_pendiente and not rec.outstanding_defaults:
                rec.outstanding_defaults = json.dumps(rec.get_base_config_json(), indent=4)

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

    def enviar_correo(self, company_id, template_name):
        for rec in self:
            _logger.info('ENVIO REPORTE %s PARTNER %s', template_name, rec)

            try:
                with self.env.cr.savepoint():

                    template_id = self.env.ref(template_name)

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

                        if template_name == 'partner_statement_auto_mail_queue.email_template_reporte_estados_cuenta':
                            attachemnts_ids = rec.generar_pdf_estado_cuenta(company_id)
                        else:
                            attachemnts_ids = rec.generar_pdf_estado_pendientes(company_id)

                        mail_id.write({
                            'attachment_ids': [(6, 0, attachemnts_ids.ids)],
                        })

            except Exception as e:
                _logger.info('Error ENVIANDO REPORTE', e)
                msg = f"Error enviando reporte: {str(e)}"
                rec.message_post(msg)

            rec.write({
                'ultimo_envio': fields.Datetime.now(),
            })

    @api.model
    def cron_enviar_reportes(self):
        partner_estado_cuenta_ids = self.env['res.partner'].search([('enviar_estado_cuenta', '=', True)])
        partner_estado_pendiente_ids = self.env['res.partner'].search([('enviar_estado_pendiente', '=', True)])

        for company_id in self.env['res.company'].search([]):
            filter_partner_ids = partner_estado_cuenta_ids.filtered(lambda l: (company_id in l.only_company_ids) or len(l.only_company_ids) == 0)
            filter_partner_ids.enviar_correo(company_id, 'partner_statement_auto_mail_queue.email_template_reporte_estados_cuenta')

            filter_partner_ids = partner_estado_pendiente_ids.filtered(lambda l: (company_id in l.only_company_ids) or len(l.only_company_ids) == 0)
            filter_partner_ids.enviar_correo(company_id, 'partner_statement_auto_mail_queue.email_template_reporte_estados_pendiente')
