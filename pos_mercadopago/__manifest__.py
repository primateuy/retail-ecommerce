{
    "name": "POS MercadoPago Integration",
    "version": "17.0.1.0.23",
    "author": "Tu Nombre / Empresa",
    "category": "Point of Sale",
    "depends": ["base","payment_mercado_pago","pos_mercado_pago"],
    "data": [
        # Groups
        "security/ir_groups.xml",
        "security/admin/ir.model.access.csv",
        "security/ir.model.access.csv",
        "security/branch_manager/ir.model.access.csv",
        "data/ir_config_parameters.xml",
        "data/ir_cron.xml",
        "data/payment_method_data.xml",
        "views/res_config_settings_views.xml",
        "views/ir_config_parameter_views.xml",
        "views/pos_mercado_pago_views.xml",
        "views/pos_payment_method_views.xml",
        "views/mercado_pago_user_views.xml",
        "views/mercado_pago_applications_views.xml",
        "views/mp_payment_transaction_views.xml",
        "views/store_branches_views.xml",
        "views/store_tills_views.xml",
        "views/business_hours_views.xml",
        "views/point_of_sale.xml",
        "views/ir_menu_views.xml",
    ],
    "assets": {
        'point_of_sale._assets_pos': [
            'pos_mercadopago/static/src/components/**/*',
            'pos_mercadopago/static/src/overrides/**/*',
        ]
    },
    "installable": True,
    "application": False,
}
