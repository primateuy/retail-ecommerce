from odoo import models, fields, api

class ShoppingPaymentMethod(models.Model):
    _name = 'shopping.payment.method'
    _description = 'Método de Pago Shopping'
    
    # Ya NO necesitas journal_id porque ahora es Many2one desde journal
    
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
    
    payment_code = fields.Selection([
        ('00', 'Contado'),
        ('17', 'Otros créditos (no tarjetas)'),
        ('20', 'OCA Card'),
        ('36', 'Diners'),
        ('37', 'American Express'),
        ('45', 'VISA'),
        ('48', 'VISA BROU Débito Para Vos'),
        ('49', 'VISA BROU Crédito Para Vos'),
        ('53', 'Master Card'),
        ('60', 'Cabal'),
        ('85', 'Vales Obsequio Costa Urbana'),
        ('90', 'Otros créditos (en tarjeta)'),
        ('91', 'Tarjetas de débito'),
        ('92', 'Tarjeta de débito VISA'),
        ('93', 'Tarjeta de débito MASTER'),
        ('99', 'Créditos de la Casa'),
    ], string='Código Forma de Pago', required=True)

    def esContado(self):
        return self.payment_code == '00'
    
    # Duda con esto luego preguntar
    def esCredito(self):
        return self.payment_code in ['17', '49', '45', '53', '90', '99'];

    def esDebito(self):
        return self.payment_code in ['91', '92', '93', '20', '36', '37', '48', '60', '85'];
    
    @api.depends('shopping_code', 'payment_code')
    def _compute_name(self):
        for record in self:
            if record.shopping_code and record.payment_code:
                shopping_name = dict(record._fields['shopping_code'].selection).get(record.shopping_code)
                payment_name = dict(record._fields['payment_code'].selection).get(record.payment_code)
                record.name = f"{shopping_name} - {payment_name}"
            else:
                record.name = "Nuevo"
    
    _sql_constraints = [
        ('unique_shopping_payment', 'unique(shopping_code, payment_code)', 
         'Ya existe esta combinación de shopping y código de pago!')
    ]