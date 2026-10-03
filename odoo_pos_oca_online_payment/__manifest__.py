{
    'name': "POS OCA: excluir del post-proceso de pagos online",
    'summary': """Las transacciones del pinpad OCA no son pagos online del PDV.""",
    'description': """
Puente entre 'odoo_pos_oca' y 'pos_online_payment' (estándar de Odoo).

pos_online_payment trata toda payment.transaction con pos_order_id como un pago
online del PDV: intenta crear un account.payment y agregarlo como pago extra a la
venta. Las transacciones del pinpad OCA también tienen pos_order_id, pero el cobro
ya está registrado en pos.payment; odoo_pos_oca_core bloquea a propósito ese
account.payment y entonces el estándar levanta ValidationError. La transacción
nunca queda post-procesada y el cron «payment: post-process transactions» la
reintenta en cada corrida durante 4 días.

Se instala solo cuando están los dos módulos (auto_install): no agrega
pos_online_payment a las bases que no lo tienen.
    """,
    'author': 'PRIMATE',
    'website': 'https://www.primate.com',
    'category': 'Point of Sale',
    'version': '17.0.1.0.0',
    'depends': [
        'odoo_pos_oca',
        'pos_online_payment',
    ],
    'auto_install': True,
    'installable': True,
    'license': 'LGPL-3',
}
