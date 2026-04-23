# Shopping Webservices

Módulo de Odoo para la integración con sistemas de gestión de Shoppings de Uruguay. Permite declarar automáticamente las ventas a los webservices de cada Shopping, soportando las tecnologías **Lecueder** y **Costa Urbana**.

---

## Funcionalidades

### Declaración de ventas
- Declara facturas confirmadas al webservice del Shopping correspondiente.
- Soporta dos tecnologías de integración: **Lecueder** y **Costa Urbana**.
- Maneja ventas con **método de pago único** o **múltiples métodos de pago** (distribución de pagos).
- Declaración **automática** diaria a las 02:00 AM mediante una tarea programada.
- Declaración **manual** desde el formulario de la factura mediante botones de acción.

### Distribución de pagos
- Permite asignar el monto de cada método de pago Shopping en una factura (campo `payment_distribution`).
- Si la factura proviene de una orden POS, la distribución se genera automáticamente a partir de los pagos del PDV.
- Si un pago del PDV no tiene método Shopping asignado, se asigna automáticamente al método **Contado** del diario.
- Valida que la distribución cubra el 100% del total de la factura antes de confirmarla.

### Integración con POS
- Detecta automáticamente el método de pago Shopping correspondiente a cada pago del PDV.
- Soporta dos vías de detección:
  1. Método de pago PDV con flag `POS Shopping` y método Shopping asignado directamente.
  2. Transacción de pago OCA — lee el `shopping_payment_code` de la transacción para buscar el método Shopping.

### Promociones Shopping
- Permite marcar programas de lealtad (`loyalty.program`) como **Promoción Shopping** para incluirlas en la declaración.

### Log de declaraciones
- Cada declaración genera un registro en el modelo `ventas.log` asociado a la factura.
- Registra estado (`Éxito`, `Advertencia`, `Error`) y la respuesta completa del webservice.

---

## Modelos

### `shopping.payment.method`
Tabla maestra de métodos de pago por Shopping. Cada registro representa un método de pago aceptado en un Shopping específico.

| Campo | Descripción |
|-------|-------------|
| `shopping_code` | Shopping al que pertenece (MSC, PS, NCS, etc.) |
| `payment_code` | Código de forma de pago enviado al webservice |
| `payment_label` | Descripción del método |
| `payment_type` | Tipo: `contado`, `crédito` o `débito` |

**Shoppings soportados:**

| Código | Shopping |
|--------|----------|
| `MSC` | Montevideo Shopping Center |
| `PS` | Portones Shopping |
| `NCS` | Nuevocentro Shopping |
| `TCS` | Tres Cruces Shopping |
| `PZI` | Plaza Italia Shopping |
| `01` | Colonia Shopping |
| `02` | Mercedes Shopping |
| `03` | Salto Shopping |
| `04` | Salto Terminal |
| `05` | Paysandú Shopping |
| `06` | Minas Shopping |

---

## Configuración

### 1. Métodos de pago Shopping
Ir a **Contabilidad > Configuración > Métodos de Pago Shopping** y crear los métodos de pago para cada Shopping, asignando el código, descripción y tipo.

### 2. Configurar el diario de ventas
En **Contabilidad > Configuración > Diarios**, editar el diario del punto de venta y completar la pestaña de integración Shopping:

| Campo | Descripción |
|-------|-------------|
| `Integración con Shopping` | Activa la integración para este diario |
| `Código Shopping` | Código del Shopping asignado al punto de venta |
| `Nro Contrato` | Número de contrato con el Shopping |
| `Código Canal` | Código del canal de ventas |
| `Caja` | Identificador de la caja |
| `Código Rubro` | Rubro asignado por el Shopping |
| `Tecnología` | `Lecueder` o `Costa Urbana` |
| `URL` | URL del webservice del Shopping |
| `Usuario` | Usuario para autenticación |
| `Password` | Contraseña para autenticación |
| `Modo Homologación` | Activa el modo de prueba (no declara datos reales) |
| `Métodos de Pago Shopping` | Métodos de pago habilitados para este diario |

> Al activar la integración, todos los campos marcados son obligatorios.

### 3. Configurar métodos de pago PDV (opcional, para POS)
En **Punto de Venta > Configuración > Métodos de Pago**, activar el flag **POS Shopping** en los métodos de pago electrónicos y asignarles el método de pago Shopping correspondiente. Esto permite que al cerrar una sesión POS, la distribución de pagos se genere automáticamente.

### 4. Configurar código Shopping en marcas de pago (opcional, para OCA)
En **Configuración > Pagos > Métodos de Pago**, asignar el `Código Shopping` en las marcas (brands) de pago para que las transacciones OCA se mapeen automáticamente al método Shopping correcto.


## Generación de Factura y posterior distribución
### 1. Crear una orden de venta y generar factura, o generar factura directamente.

### 2. Rellenar campos
Se debe elegir el diario en el cuál se haya hehco la configuración de shoppings. En ambos casos se podrá ver que aparece una pestaña en las facturas llamada "Integración Shopping", la cuál tiene dos vistas posibles.

VISTA NUMERO 1: Si es un unico metodo de pago entonces simplemente se mostrará el estado del envio al shopping.

VISTA NUMERO 2: En caso de de que el diario seleccionado tenga multiples metodos de pago se debe asignar la cantidad que se asignará a cada pago. Se puede seleccionar en porcentaje o de forma númerica.

### 3. Confirmar
Una vez rellenado estos campos se podrá confirmar la factura. Aparecerá un pop-up que indicará que se ha integrado correctamente la compra a la api del shopping respectivo.

---

## Flujo de declaración

```
Factura confirmada (state = posted)
    │
    ├── ¿Es de POS? → Genera payment_distribution automáticamente desde los pagos del PDV
    │
    ├── Tarea programada (02:00 AM) o botón manual
    │       │
    │       ├── ¿Único método de pago en el diario?
    │       │       └── declararVentaUnicoMetodo()
    │       │
    │       └── ¿Múltiples métodos?
    │               └── declararVentaVariosMetodos() — requiere payment_distribution completo
    │
    ├── Según tecnología del diario:
    │       ├── Lecueder → llama al webservice SOAP de Lecueder
    │       └── Costa Urbana → llama al webservice REST de Costa Urbana
    │
    └── Resultado:
            ├── Éxito → estadoEnvio = 'enviado', se registra en ventas.log
            └── Error → estadoEnvio = 'error', se registra en ventas.log
```


---



## Tarea programada

El módulo incluye una tarea programada `cron_evaluar_ventas_shopping` que se ejecuta **diariamente a las 02:00 AM** y declara todas las facturas confirmadas con `estadoEnvio = 'noenviado'` pertenecientes a diarios con integración Shopping activa.

---

## Dependencias

| Módulo | Tipo | Uso |
|--------|------|-----|
| `base`, `web` | Nativo Odoo | Base |
| `account`, `account_accountant` | Nativo Odoo (Enterprise) | Facturas y diarios |
| `sale_management` | Nativo Odoo | Gestión de ventas |
| `loyalty` | Nativo Odoo | Programas de lealtad / promociones |
| `payment` | Nativo Odoo | Métodos y transacciones de pago |
| `l10n_uy` | Nativo Odoo | Localización Uruguay |
| `l10n_uy_edi` | Nativo Odoo (Enterprise) | Datos del CFE (tipo, serie, número) |
| `odoo_pos_oca` | Tercero (PRIMATE) | Integración POS con terminales OCA |

---

## Autor

**Avance Software** — https://avancesoftware.us/
