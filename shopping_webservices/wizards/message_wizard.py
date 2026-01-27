from odoo import fields, api, models;


class MessageWizard(models.TransientModel):
    _name = 'message.wizard'
    _description = 'Message Wizard'

    message = fields.Text(string="Message", readonly=True)


    def action_close(self):
        return {'type': 'ir.actions.act_window_close'}