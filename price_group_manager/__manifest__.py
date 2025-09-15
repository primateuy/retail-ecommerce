{
    'name': 'Agrupador de Precio con Vigencia para Listas de Precios',
    'version': '17.0.2.0',
    'category': 'Sales',
    'summary': 'Permite aplicar reglas de lista de precios según agrupadores de precio con vigencia temporal',
    'description': """
        Este módulo permite aplicar reglas de lista de precios según un nuevo criterio 
        denominado Agrupador de Precio, configurable en el producto y con vigencia.
        
        Características principales:
        - Creación de agrupadores de precio personalizados
        - Asignación de agrupadores a productos con vigencia temporal
        - Herencia automática entre template y variantes de productos
        - Integración con reglas de lista de precios
        - Validaciones de vigencia sin superposición
        - Sincronización manual entre template y variantes
    """,
    'author': 'PrimateUy',
    'website': 'https://www.primate.com.uy',
    'depends': [
        'base',
        'product',
        'sale',
        'stock',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/price_group_views.xml',
        'views/product_views.xml',
        'views/pricelist_views.xml',
        'data/price_group_data.xml',
    ],
    'application': True,
    'license': 'LGPL-3',
}
