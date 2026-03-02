from odoo import _, api, fields, models, tools
from odoo.exceptions import ValidationError

message = "Wrong format, you need to load the time as follows: hh:mm, for example, 09:00, 12:00, 15:00"
class BusinessHours(models.Model):

    _name = 'business.hours'
    _description = 'Business hours of a store'

    day = fields.Selection([
        ('sunday', 'Sunday'),
        ('monday', 'Monday'),
        ('tuesday', 'Tuesday'),
        ('wednesday', 'Wednesday'),
        ('thursday', 'Thursday'),
        ('friday', 'Friday'),
        ('saturday', 'Saturday'),
    ], required=True)

    open_hour = fields.Char(required=True)
    close_hour = fields.Char(required=True)
    store_branch_id = fields.Many2one(
        'store.branches',
        string='Store Branch',
        required=True
    )

    # Validacion de la hora de entrada
    @api.constrains("open_hour")
    def _open_hour_constrains(self):
        for record in self:
            record.validate_hour_format(record.open_hour)

    # Validacion de la hora de salida
    @api.constrains("close_hour")
    def _close_hour_constrains(self):
        for record in self:
            record.validate_hour_format(record.close_hour)
        
    def validate_hour_format(self, hour):
        if len(hour) != 5 or ":" not in hour:
            raise ValidationError(_(message))
