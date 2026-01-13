# Módulo OCA POS Promociones

## Descripción

Módulo de prueba de concepto (POC) para implementar promociones en pagos OCA basadas en datos de tarjeta.

Este módulo extiende `odoo_pos_oca` para:
- Capturar datos de tarjeta antes de autorizar (Acquirer, Issuer, CardNumber)
- Aplicar descuentos basados en tipo de tarjeta
- Agregar líneas de descuento a las órdenes POS
- Confirmar transacciones con montos modificados

Basado en la documentación **POSLink v135, sección 3.2 - Venta simple (con promociones)**

## Dependencias

- `odoo_pos_oca` (módulo base de integración OCA)
- `point_of_sale`
- `payment`

## Instalación

1. Copiar el módulo a la carpeta de addons
2. Actualizar la lista de aplicaciones en Odoo
3. Instalar el módulo "POS OCA Promociones"

## Configuración

### 1. Producto de Descuento

Antes de usar las promociones, es necesario:

1. Crear un producto en Odoo para registrar descuentos
   - Código sugerido: `DESCUENTO_PROMOCION_OCA`
   - O configurar el campo `discount_product_id` en el método de pago OCA

2. Configurar el producto en el método de pago:
   - Ir a: Punto de Venta > Configuración > Métodos de Pago
   - Seleccionar el método de pago OCA
   - En el campo "Producto de Descuento", seleccionar el producto creado

### 2. Activar Promociones

Por defecto, el módulo está configurado para **no aplicar promociones** (POC).

Para activar promociones, editar el método `get_promotion_info()` en:
`models/pos_payment_method.py`

Ejemplo de activación (descomentar y configurar):
```python
# Ejemplo: Descuento del 10% para VISA
if acquirer == 'VISA':
    pos_order = self.env['pos.order'].search([
        ('session_id', '=', pos_session_id)
    ], order='id desc', limit=1)
    
    if pos_order:
        discount_percent = 10.0  # 10%
        discount_amount = pos_order.amount_total * (discount_percent / 100.0)
        
        return {
            'hasPromotion': True,
            'discountAmount': discount_amount,
            'productId': discount_product.id,
            'description': f'Descuento Promoción {acquirer} - {discount_percent}%'
        }
```

## Flujo de Funcionamiento

1. **Usuario inicia pago OCA** → Frontend envía `processFinancialPurchase` con `NeedToReadCard: true`

2. **POS captura tarjeta** → Responde con `ResponseCode = 12` + datos de tarjeta (Acquirer, Issuer, CardNumber)

3. **Frontend detecta `ResponseCode = 12`** → Llama a `processPromotionAndConfirm()`

4. **Backend calcula promoción** → `get_promotion_info()` determina si hay descuento

5. **Si hay promoción:**
   - Backend agrega línea de descuento → `add_promotion_discount_line()`
   - Backend recalcula totales → `get_order_totals()`
   - Frontend prepara datos de confirmación → `prepareConfirmData()`
   - Frontend llama a confirmación → `confirmFinancialPurchase()`

6. **Backend confirma con POS** → `processConfirmFinancialPurchase()` envía nuevos valores

7. **POS procesa autorización** → Con monto modificado

8. **POS responde resultado final** → `ResponseCode = 0` (éxito) o error

9. **Frontend procesa resultado** → Flujo normal continúa

## Archivos Principales

### Backend
- `models/pos_payment_method.py` - Métodos para confirmación y promociones
- `models/pos_order.py` - Métodos para agregar líneas de descuento

### Frontend
- `static/src/app/payment_oca_promociones.js` - Extensión de PaymentOCA con lógica de promociones

### Vistas
- `views/pos_payment_method_views.xml` - Campo para producto de descuento

## Limitaciones de la POC

1. **Lógica de promoción simple:** No implementa sistema completo de reglas
2. **Sin validaciones complejas:** No valida condiciones complejas (monto mínimo, productos específicos, etc.)
3. **Sin historial:** No guarda historial de promociones aplicadas
4. **Sin reversión automática:** Si falla la confirmación, el descuento ya está en la orden

## Próximos Pasos (Post-POC)

Si la POC es exitosa, considerar:
1. Sistema completo de reglas de promoción
2. Configuración de promociones por interfaz
3. Validaciones más complejas
4. Historial y reportes de promociones
5. Reversión automática en caso de errores
6. Soporte para múltiples promociones simultáneas

## Notas Técnicas

- El módulo usa `patch` de Odoo para extender la clase `PaymentOCA` sin modificar el módulo base
- Los totales de la orden se recalculan automáticamente después de agregar la línea de descuento
- Si falla cualquier paso del proceso de promoción, el sistema continúa sin descuento
- Los logs detallados están disponibles para debugging

## Autor

PRIMATE

## Licencia

LGPL-3

