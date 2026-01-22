from odoo import fields, api, models;


class MessageWizard(models.TransientModel):
    _name = 'message.wizard'
    _description = 'Message Wizard'

    message = fields.Text(string="Message", readonly=True)