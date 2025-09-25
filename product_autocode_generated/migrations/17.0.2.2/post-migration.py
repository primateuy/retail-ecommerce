import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    _logger.info("Iniciando post-migración PRODUCT AUTO CODE %s", version)
    env = api.Environment(cr, SUPERUSER_ID, {})
    product_template_ids = env['product.template'].search([
        ('auto_code_enabled', '=', True),
        ('code_domain_id', '=', False),
    ])
    product_template_ids.write({
        'code_domain_id': env.ref('product_autocode_generated.default_code_domain').id
    })
    _logger.info("TERMINADO post-migración PRODUCT AUTO CODE %s", version)
