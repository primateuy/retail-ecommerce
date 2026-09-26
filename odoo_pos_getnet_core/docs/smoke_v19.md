# Smoke contra el concentrador — backend v19

> # 🔴 PENDIENTE: primera corrida verde contra el concentrador
>
> **Instalar y configurar puede arrancar con el push. NADIE PASA UNA TARJETA hasta que esta línea
> diga verde**, con su fecha y hora.
>
> | | |
> |---|---|
> | Estado | **PENDIENTE** — el 26/09/2026 el concentrador de integración devolvía 502/504 |
> | Primera corrida verde | *(sin fecha todavía)* |
>
> **Semáforo antes de reintentar** — si esto no da `HTTP 200`, no hace falta postear nada:
>
> ```bash
> curl -s -o /dev/null -w "%{http_code}\n" \
>   https://testing-concentrador.getnet.com.uy/Concentrador/TarjetasTransaccion_401.svc?wsdl
> ```
>
> Cuando dé 200, correr el smoke y **actualizar este bloque con la fecha y la hora** de la corrida
> verde. Mientras tanto, la validación con pinpad del
> `checklist_validacion_v19_backend.md` **no arranca**.

Registro de cada tanda de posteos **reales** desde la base v19. Se anota siempre, aunque salga mal:
del otro lado queda rastro y alguien va a preguntar.

El script está en el scratchpad de la sesión (`smoke_getnet_v19.py`) y es re-ejecutable. Arma el
payload **con el código del módulo v19** (`account.payment._getnet_prepare_transaccion_vals`), no
con un payload escrito para la prueba: si el módulo se equivoca, la prueba se equivoca igual.

**El hash nunca se escribe acá ni se imprime.** Se lee del proveedor ya configurado y se inyecta en
la base de pruebas.

---

## Tanda 1 — 26/09/2026, 17:16 a 17:16 (hora local)

| dato | valor |
|---|---|
| base | `o19_getnet_test` |
| concentrador | `https://testing-concentrador.getnet.com.uy` (integración) |
| EmpCod / TermCod | `PRIMA1` / `T00001` |
| coordinación | ninguna pendiente: las pruebas de v17 están pausadas y `T00001` estaba libre |

**Resultado: NO SE PUDO COMPLETAR. El concentrador de integración no está respondiendo.**

```
[17:16:07] payload del módulo v19: {EmpCod PRIMA1, TermCod T00001, MonedaISO 0840,
                                    Operacion VTA, Monto 1700, FacturaNro 0}
[17:16:07] 1/4 PostearTransaccion  -> rc=999  HTTP 502 del concentrador
[17:16:11] 2-3/4 ConsultarTransaccion / CancelarTransaccion: SALTEADOS (no hubo token)
[17:16:21] 4/4 PostearConsultaUltimoCierre -> rc=999  HTTP 504 del concentrador
[17:16:21] terminal liberada
```

Se comprobó que **no es nuestro extremo**: la propia URL del WSDL devuelve 502/504, y también la
raíz del sitio, que no puede ser un problema de ruta.

```
14:17:36  GET Concentrador/TarjetasTransaccion_401.svc?wsdl -> HTTP 504
14:17:36  GET Concentrador/TarjetasCierre_400.svc?wsdl      -> HTTP 504
14:18:17  (reintento 40 s después)                          -> HTTP 502 en las dos
```

DNS y TCP sí responden (`52.45.20.219`, puertos 443 y 80 abiertos): el gateway está en pie y el
servicio detrás no.

### Lo que SÍ quedó verificado con esta tanda

No es una corrida perdida — llegó hasta la capa HTTP y eso ejercita todo lo de este lado:

- **El payload del módulo v19 se arma bien.** `Operacion=VTA`, `Monto` en centavos (17,00 → 1700),
  `TermCod` de la terminal elegida y **`FacturaNro=0`** por no haber factura origen, sin los
  `FacturaMonto*`. Es exactamente el criterio de New Age Data.
- **El cliente SOAP del núcleo resuelve, arma el sobre y postea** contra la URL correcta.
- **El camino de error de transporte se comporta como está diseñado:** un HTTP 5xx **no levanta
  excepción**; vuelve como respuesta sintética `rc=999` con el mensaje, que es lo que permite que
  el motor de polling decida en vez de cortar. El manual del WS obliga a consultar hasta obtener
  respuesta, y esto es lo que lo hace posible.
- **La terminal quedó liberada** en el `finally`, sin lock colgado.

### Lo que queda pendiente de esta tanda

- `PostearTransaccion` con respuesta real y su `TokenNro`.
- `ConsultarTransaccion` y `CancelarTransaccion` sobre ese token.
- `PostearConsultaUltimoCierre` con datos.

**Cómo repetirla:** volver a correr el script cuando el concentrador esté arriba. Verificarlo antes
es un `GET` al WSDL — si devuelve 502/504, no hace falta postear nada.

### Dato de configuración que salió a la luz

La compañía de `o19_getnet_test` tiene **USD** como moneda, así que el payload salió con
`MonedaISO=0840`. Para una prueba con pinpad conviene que la compañía esté en UYU (`0858`) o
elegir la moneda a mano en el pago. Y es el mismo tema que la **tasa del día** de la guía de
instalación: sin ella no se confirma ningún pago, ni siquiera en pesos.
