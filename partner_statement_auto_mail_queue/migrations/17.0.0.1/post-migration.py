import logging
import json
from odoo import api, SUPERUSER_ID

_logger = logging.getLogger("MIGRATION")


def migrate(cursor, version):
    _logger.info('********** EXECUTE POST MIGRATION 17.0.0.1 ***************')

    env = api.Environment(cursor, SUPERUSER_ID, {})

    partners_ids = env['res.partner'].search([
        '|',
        ('statement_defaults', '!=', False),
        ('outstanding_defaults', '!=', False),
    ])

    _logger.info('Updating statement_defaults for %s partners', len(partners_ids))

    info = {
        "show_aging_buckets": False,
        "filter_non_due_partners": True,
        "account_type": 'asset_receivable',
        "aging_type": 'months',
        "filter_negative_balances": True,
    }

    for rec in partners_ids:
        rec.statement_defaults = json.dumps(info, indent=4)
        rec.outstanding_defaults = json.dumps(info, indent=4)

    _logger.info('********** END POST MIGRATION 17.0.0.1 ***************')
