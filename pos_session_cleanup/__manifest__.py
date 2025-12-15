{
    'name': "POS Session Cleanup",
    'summary': """Permite cerrar sesiones de POS desvinculando pos.order en borrador""",
    'description': """
        Este módulo permite cerrar sesiones del punto de venta desvinculando automáticamente
        las pos.order (órdenes del punto de venta) que se encuentren en estado borrador y estén
        asociadas a la sesión que se está cerrando.
        
        Características:
        - Desvincula pos.order en borrador de la sesión del POS
        - Agrega comentarios explicativos en cada pos.order desvinculada
        - Permite cerrar la sesión sin errores por pos.order asociadas
        - Botón para limpieza manual de pos.order en sesiones abiertas
        - Funciona desde el backend sin necesidad de JavaScript
    """,
    'author': 'PRIMATE',
    'website': 'https://www.primate.com',
    'category': 'Point of Sale',
    'version': '17.0.1.0.0',
    'depends': [
        'base',
        'point_of_sale',
    ],
    'data': [
        'data/pos_session_cleanup_data.xml',
        'views/pos_session_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
    'license': 'LGPL-3',
} 