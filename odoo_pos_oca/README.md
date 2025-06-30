# Módulo OCA POS - Integración con Punto de Venta

Este módulo proporciona integración completa con el sistema OCA para el punto de venta de Odoo, incluyendo todas las configuraciones necesarias para el funcionamiento del sistema de pagos.

## Características Principales

### 1. Configuraciones Automáticas de Instalación

Al instalar el módulo, se configuran automáticamente los siguientes elementos:

#### Proveedor de Pago OCA
- **Nombre**: OCA
- **Código**: oca
- **Estado**: Modo de prueba (test)
- **Tokenización**: Habilitada
- **Métodos de pago**: Configurado con el método OCA

#### Diario de Pago OCA
- **Nombre**: OCA
- **Código**: OCA
- **Tipo**: Banco
- **Moneda**: Peso Uruguayo (UYU)
- **Métodos de pago entrantes**: OCA
- **Métodos de pago salientes**: OCA

#### Método de Pago OCA
- **Nombre**: OCA
- **Código**: oca
- **Tipo**: Entrante (inbound)
- **Proveedores**: Configurado con el proveedor OCA

#### Método de Pago POS OCA
- **Nombre**: OCA
- **Terminal de pago**: OCA
- **Cuenta por cobrar**: Configurada automáticamente
- **Configuraciones específicas**:
  - URL del webservice: https://api.oca.com
  - Código de sistema: 1
  - Código de terminal: 001
  - Client App ID: 1
  - Código de sucursal: 1

### 2. Integración con Métodos de Pago Estándar

El módulo utiliza el sistema estándar de métodos de pago de Odoo (`payment.method`) para gestionar los diferentes tipos de tarjetas:

#### Métodos de Pago Soportados
- **Visa**: Método de pago estándar de Odoo
- **Mastercard**: Método de pago estándar de Odoo
- **American Express**: Método de pago estándar de Odoo
- **OCA**: Método de pago específico del módulo

#### Mapeo de Códigos OCA
El módulo incluye mapeo automático de códigos OCA a métodos de pago estándar:

| Código OCA | Método de Pago |
|------------|----------------|
| 5 | Visa |
| 6 | Mastercard |
| 7 | American Express |
| 21 | OCA |

### 3. Transacciones de Pago

El módulo almacena información completa de todas las transacciones OCA, incluyendo:

#### Campos Principales
- **POS ID**: Identificador del punto de venta
- **BIN de Tarjeta**: Primeros 6 números de la tarjeta
- **Últimos 4 dígitos**: Últimos 4 dígitos de la tarjeta
- **Código del Emisor**: Código del emisor de la tarjeta
- **Nombre del Emisor**: Nombre del emisor de la tarjeta
- **Cantidad de Cuotas**: Número de cuotas de la transacción
- **Adquirente**: Proveedor de pago (Acquirer)
- **Número de Ticket**: Número de ticket de la transacción
- **Número de Lote**: Número de lote de la transacción
- **Código de Autorización**: Código de autorización de la transacción
- **Número de Comercio**: Número de comercio para el adquirente
- **Número de Factura**: Número de factura enviado al POS

#### Campos de Auditoría
- **ID Transacción OCA**: ID interno de la transacción OCA
- **Código de Respuesta OCA**: Código de respuesta del sistema OCA
- **Mensaje de Respuesta OCA**: Mensaje de respuesta del sistema OCA
- **Respuesta Completa del POS**: Respuesta completa del POS en formato JSON

#### Relaciones
- **Origen de Transacción**: Pago POS, Pedido POS u Otro
- **Pedido POS**: Pedido del punto de venta que generó la transacción
- **Pago POS**: Pago del punto de venta que generó la transacción
- **Es Promoción**: Indica si la transacción es una promoción

### 4. Configuraciones del Sistema

#### Parámetros de Configuración
- **oca.default_url**: URL por defecto del API OCA
- **oca.default_timeout**: Timeout por defecto (30 segundos)
- **oca.retry_attempts**: Número de intentos de reintento (3)
- **oca.default_merchant_number**: Número de comercio por defecto

#### Seguridad
El módulo utiliza los grupos de seguridad estándar de Odoo:
- **Usuarios**: `base.group_user` - Permisos básicos para usuarios
- **Administradores de Contabilidad**: `account.group_account_manager` - Permisos completos para administradores

## Instalación

1. **Instalar el módulo**: El módulo se instala normalmente a través del sistema de módulos de Odoo.

2. **Configuración automática**: Todas las configuraciones se aplican automáticamente durante la instalación.

3. **Verificación**: Después de la instalación, verificar que:
   - El proveedor de pago OCA esté configurado en Configuración > Pagos > Proveedores de Pago
   - El diario de pago OCA esté configurado en Contabilidad > Configuración > Diarios
   - El método de pago POS OCA esté disponible en Punto de Venta > Configuración > Métodos de Pago
   - Los métodos de pago estándar (Visa, Mastercard, etc.) estén configurados en Configuración > Pagos > Métodos de Pago

## Configuración Manual (Opcional)

### Configurar Método de Pago POS
1. Ir a Punto de Venta > Configuración > Métodos de Pago
2. Editar el método de pago OCA
3. Configurar los parámetros específicos:
   - URL del webservice
   - Código de sistema
   - Código de terminal
   - Código de sucursal

### Configurar Métodos de Pago Estándar
1. Ir a Configuración > Pagos > Métodos de Pago
2. Verificar que los métodos Visa, Mastercard y American Express estén configurados
3. Configurar parámetros específicos según sea necesario

### Configurar Proveedor de Pago
1. Ir a Configuración > Pagos > Proveedores de Pago
2. Editar el proveedor OCA
3. Configurar parámetros específicos del proveedor

## Uso

### Procesamiento de Pagos
1. **Configurar método de pago**: Asegurar que el método de pago OCA esté habilitado en la configuración del POS.
2. **Procesar pago**: Los pagos se procesan automáticamente a través del terminal OCA.
3. **Verificar transacción**: Las transacciones se registran automáticamente en el sistema.

### Consulta de Transacciones
1. **Ver transacciones**: Ir a Contabilidad > Pagos > Transacciones OCA
2. **Filtrar**: Usar los filtros disponibles para buscar transacciones específicas
3. **Ver detalles**: Hacer clic en una transacción para ver todos los detalles

### Gestión de Métodos de Pago
1. **Ver métodos de pago**: Ir a Configuración > Pagos > Métodos de Pago
2. **Configurar métodos**: Editar cada método de pago según sea necesario
3. **Asociar con proveedores**: Configurar qué métodos de pago usa cada proveedor

## Mantenimiento

### Logs
El módulo genera logs detallados para facilitar el debugging:
- Logs de transacciones
- Logs de configuración
- Logs de errores

### Actualizaciones
Al actualizar el módulo:
1. Se ejecutan automáticamente los hooks de post-instalación
2. Se verifican y actualizan las configuraciones
3. Se mantienen los datos existentes

## Soporte

Para soporte técnico o consultas sobre el módulo, contactar al equipo de desarrollo de PRIMATE.

## Licencia

Este módulo está licenciado bajo LGPL-3.

## Estructura del Módulo

```
odoo_pos_oca/
├── models/
│   ├── __init__.py
│   ├── pos_payment_method.py      # Lógica principal de integración
│   ├── payment_transaction.py     # Extensión de payment.transaction
│   ├── pos_payment.py            # Extensión de pos.payment
│   └── pos_session.py            # Extensión de pos.session
├── views/
│   ├── pos_payment_method_views.xml
│   ├── pos_payment_views.xml
│   └── payment_transaction_views.xml
├── data/
│   ├── payment_provider_data.xml  # Datos del proveedor
│   ├── oca_config_data.xml       # Configuraciones OCA
│   ├── oca_installation_data.xml # Datos de instalación
│   └── pos_payment_method_data.xml # Datos del método POS
├── security/
│   └── ir.model.access.csv       # Permisos usando grupos estándar
├── hooks.py                      # Hook de post-instalación
└── __manifest__.py
```

## Notas Técnicas

- **Optimización**: El código está optimizado para el rendimiento con comentarios detallados
- **Legibilidad**: Código estructurado y comentado para facilitar el mantenimiento
- **Compatibilidad**: Compatible con Odoo 17.0
- **ORM**: Utiliza el ORM de Odoo para todas las operaciones de base de datos
- **Manejo de Errores**: Incluye manejo robusto de errores y logging detallado
- **Estándares**: Utiliza los métodos de pago estándar de Odoo en lugar de entidades personalizadas
- **Seguridad**: Utiliza grupos de seguridad estándar de Odoo para mayor compatibilidad
