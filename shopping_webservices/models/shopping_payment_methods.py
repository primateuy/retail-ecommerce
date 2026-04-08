from odoo import models, fields, api

class ShoppingPaymentMethod(models.Model):
    _name = 'shopping.payment.method'
    _description = 'Método de Pago Shopping'

    name = fields.Char(string='Nombre', compute='_compute_name', store=True)

    shopping_code = fields.Selection([
        ('MSC', 'Montevideo Shopping Center'),
        ('PS', 'Portones Shopping'),
        ('NCS', 'Nuevocentro Shopping'),
        ('TCS', 'Tres Cruces Shopping'),
        ('PZI', 'Plaza Italia Shopping'),
        ('01', 'Colonia Shopping'),
        ('02', 'Mercedes Shopping'),
        ('03', 'Salto Shopping'),
        ('04', 'Salto Terminal'),
        ('05', 'Paysandú Shopping'),
        ('06', 'Minas Shopping'),
    ], string='Shopping', required=True)

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

    @api.depends('shopping_code', 'payment_code', 'payment_label')
    def _compute_name(self):
        shopping_selection = dict(self._fields['shopping_code'].selection)
        for record in self:
            if record.shopping_code and record.payment_code:
                shopping_name = shopping_selection.get(record.shopping_code, record.shopping_code)
                payment_desc = record.payment_label or record.payment_code
                record.name = f"{shopping_name} - {payment_desc}"
            else:
                record.name = "Nuevo"

    _sql_constraints = [
        ('unique_shopping_payment', 'unique(shopping_code, payment_code)',
         'Ya existe esta combinación de shopping y código de pago!')
    ]
