"""
Migración 0.2: payment_code cambia de Selection a Char.

Odoo guarda en ir_model_fields_selection los valores de un campo Selection.
Al cambiar el tipo a Char, el proceso de upgrade intenta eliminar esos registros
y falla porque busca 'ondelete' en un campo Char. Este script los elimina
antes de que Odoo intente hacerlo.
"""


def migrate(cr, version):
    # Eliminar los valores de selección del antiguo campo payment_code
    cr.execute("""
        DELETE FROM ir_model_fields_selection
        WHERE field_id = (
            SELECT id FROM ir_model_fields
            WHERE model = 'shopping.payment.method'
              AND name = 'payment_code'
        )
    """)

    # Actualizar el tipo del campo en ir_model_fields para evitar conflictos
    cr.execute("""
        UPDATE ir_model_fields
        SET ttype = 'char'
        WHERE model = 'shopping.payment.method'
          AND name = 'payment_code'
    """)
