{
    "name": "POS Forum - Employee Controls",
    "summary": "Employee permissions for POS buttons",
    "description": """
        Agrega permisos por empleado para mostrar botones del POS
        y habilita busqueda por documento en el selector de vendedores.
    """,
    "author": "PRIMATE UY",
    "website": "https://www.primateuy.com",
    "category": "Point of Sale",
    "version": "17.0.1.0.0",
    "depends": [
        "point_of_sale",
        "pos_hr",
        "pw_pos_salesperson_emp",
    ],
    "data": [
        "views/hr_employee_views.xml",
    ],
    "assets": {
        "point_of_sale._assets_pos": [
            "pos_forum_employee_controls/static/src/overrides/**/*",
        ],
    },
    "license": "LGPL-3",
    "installable": True,
    "application": False,
}
