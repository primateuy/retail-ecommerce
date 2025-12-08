# POS Session Cleanup

## Descripción

Este módulo permite cerrar sesiones del punto de venta (POS) eliminando automáticamente las pos.order (órdenes del punto de venta) que se encuentren en estado borrador y estén asociadas a la sesión que se está cerrando.

## Características

- **Eliminación automática**: Al cerrar una sesión de POS, se eliminan automáticamente todas las pos.order en borrador asociadas a esa sesión.
- **Permite cerrar sesiones**: Permite cerrar la sesión sin errores por pos.order asociadas en borrador.
- **Limpieza manual**: Botón para realizar limpieza manual de pos.order en sesiones abiertas.
- **Funciona desde el backend**: La limpieza se ejecuta automáticamente desde el backend sin necesidad de JavaScript.
- **Maneja errores específicos**: Resuelve el error "No puede cerrar el PdV cuando las ordenes aun estan en estado de borrador".

## Funcionalidades

### 1. Limpieza automática al cerrar sesión

Cuando se intenta cerrar una sesión de POS (desde cualquier lugar), el módulo:

1. Busca todas las pos.order en borrador asociadas a la sesión
2. Elimina estas pos.order de la sesión
3. Permite el cierre normal de la sesión

### 2. Manejo de errores específicos

El módulo intercepta y maneja específicamente:
- **Error de órdenes en borrador**: "No puede cerrar el PdV cuando las ordenes aun estan en estado de borrador"
- **Validación de sesión**: Limpia pos.order antes de la validación de sesión
- **Validación desde POS**: Limpia pos.order antes de la validación desde el frontend del POS

### 3. Limpieza manual

- Botón "Limpiar Pos Orders" en sesiones abiertas
- Confirmación antes de proceder
- Notificación de resultados

## Instalación

1. Copiar el módulo al directorio de addons de Odoo
2. Actualizar la lista de aplicaciones
3. Instalar el módulo "POS Session Cleanup"

## Uso

### Cerrar una sesión de POS

El módulo funciona automáticamente cuando se intenta cerrar una sesión de POS desde cualquier lugar:

1. **Desde la interfaz web**: Ir a **Punto de Venta > Sesiones** y hacer clic en "Cerrar sesión"
2. **Desde el POS**: Cerrar sesión desde el punto de venta
3. **Programáticamente**: Cualquier llamada a los métodos de cierre de sesión

El módulo automáticamente:
- Busca pos.order en borrador asociadas a la sesión
- Las elimina de la sesión
- Permite el cierre normal de la sesión

### Manejo de errores específicos

El módulo intercepta y resuelve automáticamente:
- **Error de órdenes en borrador**: Elimina las pos.order antes de mostrar el error
- **Validaciones de sesión**: Permite el cierre después de limpiar pos.order
- **Validación desde POS**: Limpia pos.order antes de la validación desde el frontend

### Limpieza manual de pos.order

1. Ir a **Punto de Venta > Sesiones**
2. Seleccionar una sesión abierta
3. Hacer clic en "Limpiar Pos Orders"
4. Confirmar la acción
5. Se mostrará una notificación con el resultado

## Logs

El módulo registra las operaciones de limpieza en los logs de Odoo:

- Información sobre pos.order encontradas para eliminar
- Confirmación de eliminación de pos.order
- Resumen de la operación de limpieza

## Dependencias

- `base`
- `point_of_sale`

## Versión

17.0.1.0.0

## Autor

PRIMATE

## Licencia

LGPL-3 