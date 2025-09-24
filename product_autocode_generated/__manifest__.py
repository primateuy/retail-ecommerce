{
    "name": "Product Auto Code V2",
    "version": "17.0.2.1",
    "category": "Inventory/Product",
    "summary": "Sistema avanzado de generación automática de códigos para productos y variantes",
    "description": """
        Módulo para la generación automática de códigos de referencia para productos y variantes.
        
        Características principales:
        - Generación automática de códigos basada en categorías y dominios
        - Sistema de atributos configurable para variantes
        - Configuración global del sistema
        - Validaciones de unicidad y longitud
        - Interfaz intuitiva y fácil de usar
        
        Desarrollado siguiendo las mejores prácticas de Odoo 17.0
    """,
    "author": "PrimateUy + Diego + ChatGPT",
    "website": "https://www.grupofernandez.com",
    "license": "LGPL-3",
    "depends": [
        "product",
        "stock",
    ],
    "data": [
        "security/ir.model.access.csv",

        'views/product_category_views.xml',
        'views/product_attribute_views.xml',
        'views/product_code_domain_views.xml',
        'views/product_template_views.xml',
        'views/product_product_views.xml',
        "views/res_config_settings_views.xml",

        "data/product_auto_code_actions.xml",
        "data/default_data.xml",
    ],
    "application": False,
} 