from odoo import models, fields, api

class AccountJournal(models.Model):
    _inherit = 'account.journal'

    
    codigoShopping = fields.Char(string="Código Shopping", help="Código asignado por el shopping para identificar este punto de venta en sus sistemas.")
    nroContrato = fields.Char(string="Nro Contrato", help="Número de contrato asociado a este punto de venta en el shopping.")
    codigoCanal = fields.Char(string="Código Canal", help="Código del canal de ventas asignado por el shopping.")
    caja = fields.Char(string="Caja", help="Identificador de la caja registradora asociada a este punto de venta.")
    codigoRubro = fields.Char(string="Código Rubro", help="Código de rubro asignado por el shopping para este punto de venta.")
    tecnologia = fields.Selection([
        ('lecueder', 'Lecueder'),
        ('costa_urbana', 'Costa Urbana'),
    ], string="Tecnología", default='lecueder');

    homologacion = fields.Boolean(
        string="Modo Homologación", default=False);

    shopping_payment_method_ids = fields.Many2many(
        'shopping.payment.method',
        'journal_shopping_payment_rel',  # Nombre de la tabla intermedia
        'journal_id',                     # Columna para journal
        'payment_method_id',              # Columna para payment method
        string='Métodos de Pago Shopping'
    )