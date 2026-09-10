from odoo import models, fields, api
from odoo.exceptions import ValidationError

class AccountJournal(models.Model):
    _inherit = 'account.journal'

    integracionShopping = fields.Boolean(
        string="Integración con Shopping", default=False);
    codigoShopping = fields.Char(string="Código Shopping", help="Código asignado por el shopping para identificar este punto de venta en sus sistemas.")
    nroContrato = fields.Char(string="Nro Contrato", help="Número de contrato asociado a este punto de venta en el shopping.")
    codigoCanal = fields.Char(string="Código Canal", help="Código del canal de ventas asignado por el shopping.")
    caja = fields.Char(string="Caja", help="Identificador de la caja registradora asociada a este punto de venta.")
    codigoRubro = fields.Char(string="Código Rubro", help="Código de rubro asignado por el shopping para este punto de venta.")
    tecnologia = fields.Selection([
        ('lecueder', 'Lecueder'),
        ('costa_urbana', 'Costa Urbana'),
    ], string="Tecnología", default='lecueder');
    secuencial_ventas = fields.Integer(string="Secuencial Ventas", default=0, help="Secuencial para las ventas realizadas a través del shopping.")
    usuario = fields.Char(string="Usuario", help="Usuario para autenticar en el servicio web del shopping.")
    url = fields.Char(string="URL", help="URL del servicio web proporcionado por el shopping para la integración.")
    password = fields.Char(string="Password", help="Contraseña para autenticar en el servicio web del shopping.")

    homologacion = fields.Boolean(
        string="Modo Homologación", default=False);

    shopping_payment_method_ids = fields.Many2many(
        'shopping.payment.method',
        'journal_shopping_payment_rel',  # Nombre de la tabla intermedia
        'journal_id',                     # Columna para journal
        'payment_method_id',              # Columna para payment method
        string='Formas de Pago Shopping'
    )

    def write(self, vals):
        for record in self:
            integracion_activa = vals.get('integracionShopping', record.integracionShopping)
            
            if integracion_activa:
                codigo_shopping = vals.get('codigoShopping', record.codigoShopping)
                nro_contrato = vals.get('nroContrato', record.nroContrato)
                codigo_canal = vals.get('codigoCanal', record.codigoCanal)
                tecnologia = vals.get('tecnologia', record.tecnologia)
                url = vals.get('url', record.url)
                password = vals.get('password', record.password)
                
                if not (codigo_shopping and nro_contrato and codigo_canal and tecnologia and url and password):
                    raise ValidationError("Para activar la integración con Shopping, debe completar todos los campos requeridos: Código Shopping, Nro Contrato, Código Canal, Tecnología, URL y Password.")
        
        return super(AccountJournal, self).write(vals)
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('integracionShopping') and (not vals.get('codigoShopping') or not vals.get('nroContrato') or not vals.get('codigoCanal') or not vals.get('tecnologia') or not vals.get('url') or not vals.get('password')):
                raise ValidationError("Para activar la integración con Shopping, debe completar todos los campos requeridos: Código Shopping, Nro Contrato, Código Canal, Tecnología, URL y Password.")

        return super(AccountJournal, self).create(vals_list)
    
