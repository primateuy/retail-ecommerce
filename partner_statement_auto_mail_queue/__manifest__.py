{
    'name': "Envío Automático de Estados de Cuenta y Pendientes",
    'summary': """Envío Automático de Estados de Cuenta y Pendientes""",
    'description': """Envío Automático de Estados de Cuenta y Pendientes""",
    'author': 'ANDRES',
    'website': 'https://www.andres.com',
    'category': 'Localization',
    'version': '17.0.0.1',
    'depends': ['base', 'account', 'partner_statement', 'account_invoice_overdue_warn'],
    'data': [
        'views/res_partner_views.xml',

        'data/email_templates.xml',
        'data/cron.xml',
    ],
    'license': 'LGPL-3',
}
