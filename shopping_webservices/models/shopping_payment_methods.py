from odoo import models, fields, api

class ShoppingPaymentMethod(models.Model):
    _name = 'shopping.payment.method'
    _description = 'Método de Pago Shopping'

    name = fields.Char(string='Nombre', compute='_compute_name', store=True)

    payment_code = fields.Char(string='Código Forma de Pago', required=True)
    payment_label = fields.Char(string='Descripción')
    payment_type = fields.Selection([
        ('contado', 'Contado'),
        ('credito', 'Crédito'),
        ('debito', 'Débito'),
    ], string='Tipo de Pago', required=True)

    def esContado(self):
        return self.payment_type == 'contado'

    def esCredito(self):
        return self.payment_type == 'credito'

    def esDebito(self):
        return self.payment_type == 'debito'

    @api.depends('payment_label')
    def _compute_name(self):
        for record in self:
            record.name = record.payment_label or "Nuevo"

    _sql_constraints = [
        ('unique_shopping_payment', 'unique(payment_code)',
         'Ya existe un método de pago con este código!')
    ]
