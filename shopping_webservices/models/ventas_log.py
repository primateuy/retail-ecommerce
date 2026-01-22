from odoo import models, fields, api;


class VentasLog(models.Model):
    _name = 'ventas.log'
    _description = 'Log de Ventas Declaradas'
    _rec_name = 'texto'

    account_move_id = fields.Many2one('account.move', string="Asiento Contable")
    fecha_declaracion = fields.Datetime(string="Fecha de Declaración", default=fields.Datetime.now)
    estado = fields.Selection([
        ('exito', 'Éxito'),
        ('warning', 'Advertencia'),
        ('error', 'Error'),
    ], string="Estado")
    texto = fields.Text(string="Respuesta")

    