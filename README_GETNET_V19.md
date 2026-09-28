# Getnet / TransAct en Odoo 19 — estado de la rama

Rama `19.0_getnet`. Port de la integración Getnet/TransAct desde `17.0_getnet @ 2371fb1`.

## Qué entra en esta entrega

| módulo | qué es |
|---|---|
| `odoo_pos_getnet_core` | proveedor, terminal con lock entre flujos, transacción, motor de polling, cliente SOAP, cron de recuperación, cierre de lote |
| `odoo_pos_getnet_backend` | el flujo contable: cobrar y devolver desde **Contabilidad > Pagos** |
| `odoo_pos_getnet_pos_backend` | la terminal Getnet para los medios integrados del **POS Backend** de Campera (P3). Depende de `pos_backend` @ `b5cbea5`; el cobro automático usa `b20023a` |
| `odoo_pos_getnet_promociones` | **promociones por tarjeta** en el cobro del POS Backend: lectura de la tarjeta (B), selección manual (A), PROMO NO APLICADA / NO COINCIDE. Depende de `pos_backend` @ `eb18622`. Ver su `doc/promociones.md` |

## Suites

Medido el 28/09/2026 sobre la punta de la rama (fase 1 + promociones como línea de descuento), sólo resultado:

| base | módulos | resultado |
|---|---|---|
| `o19_getnet_test` (v19, `l10n_uy_einvoice_uruware`, endpoints en testing) | core + backend | **110 / 110** |
| `o19_getnet_pb_test` (copia de Campera staging, `pos_backend` @ `eb18622`) | core + backend + POS Backend + promociones + `pos_backend` entero | **690 / 690** |

```bash
odoo-bin -c <conf> -d <base> -u odoo_pos_getnet_core,odoo_pos_getnet_backend[,odoo_pos_getnet_pos_backend,odoo_pos_getnet_promociones,pos_backend] \
  --test-tags /odoo_pos_getnet_core,/odoo_pos_getnet_backend[,/odoo_pos_getnet_pos_backend,/odoo_pos_getnet_promociones,/pos_backend] \
  --stop-after-init --max-cron-threads=0
```

## Documentación

| archivo | para quién |
|---|---|
| `odoo_pos_getnet_core/docs/guia_usuario_getnet_backend.md` (+ `.pdf`) | **quien configura y usa** la integración. Sin código |
| `odoo_pos_getnet_core/docs/guia_instalacion_v19.md` | quien monta el entorno |
| `odoo_pos_getnet_core/docs/checklist_validacion_v19_backend.md` | para correr **frente al pinpad**, cuando se agende |
| `odoo_pos_getnet_core/docs/smoke_v19.md` | registro de cada tanda de posteos reales |
| `odoo_pos_getnet_core/docs/staging_checklist.md` | el de v17, que es de donde sale el de arriba |
| `doc/dual-landing.md` | arreglos que valen para las dos ramas |

## Lo que NO está, y por qué

### TPV estándar de Odoo — **paridad pendiente deliberadamente**

> **`odoo_pos_getnet_pos` (el TPV estándar de Odoo) queda fuera del criterio de cierre por decisión
> de Daryl: no se va a usar en los destinos actuales. Retomar si un cliente lo requiere.**

Es una decisión escrita, no un olvido. El módulo existe en la rama de v17 y no se portó; si algún
día hace falta, el punto de partida es ese y la sección 6.6 del checklist de v17.

### Otros

- **Puente con Fiserv** (`odoo_pos_getnet_fiserv_flags`) y **TPV estándar** (`odoo_pos_getnet_pos`):
  fuera de esta entrega, y **no instalables** en 19.0 (`installable: False`, `4a35d91`).
- **Botón en la factura**: el camino soportado es Contabilidad > Pagos. El wizard «Registrar pago»
  de la factura no sirve para este flujo y no es un defecto.
- **Refresco automático del form del pago**: hay que refrescar a mano. Backlog conocido, está
  documentado en la guía de usuario sin disimulo.
- **Validación con pinpad**: queda para el primer cobro real en producción. Lo validado contra el
  concentrador simulado, y lo que no se pudo validar, está en la sección «Validación».

## Validación — contra un concentrador SIMULADO

> **P3 y el backend se validaron contra un concentrador simulado, no contra el de New Age Data**,
> que está caído desde el 26/09/2026 (502/504 sostenido). La validación con hardware queda para el
> **primer cobro real en producción**. Decisión de Daryl, 27/09/2026.

**El simulador.** Un servidor SOAP local que implementa `TarjetasTransaccion_401` y
`TarjetasCierre_400` en las rutas del concentrador. Odoo se apuntó a él **por configuración**
(`getnet_url_webservice`), sin tocar código. Vive fuera del repo, en
`Desarrollos Documentos/Getnet Campera/simulador/` (su `ESCENARIOS.md` dice de dónde sale cada
respuesta). **Sólo 2 respuestas son capturas reales completas** (la aprobada y la tarjeta vencida
del 17/08, con el titular anonimizado) más el 504 real; **el resto está construido** con la forma de
esas capturas. El cierre con lotes es **circular**: su estructura sale del fixture de los tests, así
que el simulador le devuelve al parser lo que el parser espera.

**Qué se corrió.** Los dos checklists completos, en la UI real, con video:

| checklist | base | quién opera | resultado | video |
|---|---|---|---|---|
| `checklist_pinpad_p3.md` (7 escenarios + contingencia) | `o19_getnet_pb_test` | cajero sin Ajustes; Supervisor para forzar | **46 / 51** | `2026-09-27_1856_p3_simulador.webm` (18:25) |
| `checklist_validacion_v19_backend.md` (8 bloques) | `o19_campera_staging` | `contador.getnet`, sin Ajustes | **36 / 41** | `2026-09-27_1952_backend_simulador.webm` (19:02) |

Los videos, los resultados por verificación (`*_resultados.json`) y el log de cada llamada al
simulador (`llamadas.jsonl`, con el EmpHASH siempre como `***`) están junto al simulador. No van al
repo: pesan 72 MB y 45 MB.

**Defectos que encontró la validación, todos corregidos con su test** (sin el arreglo, el test
nuevo falla; con el arreglo, la suite completa en verde):

| | qué pasaba | commit |
|---|---|---|
| núcleo | tras un kill de Odoo a mitad de un cobro, la terminal quedaba bloqueada 10 min (TTL) en vez de 2 (heartbeat): el lock nunca estaba a nombre del token (DL-9) | `3a17e8d` |
| backend | el hilo de polling revienta como contador sin Ajustes (`AccessError` en `payment.provider`) con el cobro ya posteado (DL-10) | `71d364a` |
| backend | cobrar una factura firmada en v17 daba un error crudo del parser (DL-2b) | `41cbd38` |
| P3 | un cobro aprobado sin línea en el POS (kill antes de guardar el pedido) quedaba salteado para siempre: pasa a conciliación a los 15 min | en el `[ADD]` |
| P3 | una devolución a medias se reintentaba creando otra DEV (`UniqueViolation`), y esa excepción cortaba el cron de huérfanos para siempre | en el `[ADD]` |

**Lo que el simulador NO puede validar** (queda para el primer cobro real):

- cuánto tarda el pinpad de verdad y si la ventana de gracia de 4 s alcanza;
- el texto exacto de un rechazo real, de «no hay cierres pendientes» y del rc 9;
- la estructura real de `DatosCierre`;
- los centavos (el simulador devuelve el `Monto` que recibe);
- que el concentrador acepte el `TicketOriginal` y que el pinpad procese la DEV;
- que el pinpad no pida datos de factura con `FacturaNro=0`, y el voucher impreso;
- la corrida verde del smoke.

**Hallazgos abiertos, sin arreglar** (decisión de Daryl):

1. **«No sé» cuesta hasta 3 minutos.** Consultar, liberar un pedido o cerrar la caja con un cobro
   sin resolver usan el motor completo de consulta (hasta 180 s). El cajero espera con la pantalla
   trabada y, pasados ~170 s, la UI muestra «Se perdió la conexión». Con workers y un
   `limit_time_real` menor, esas llamadas se cortan. Además, el modal de cierre no avisa del
   pedido con cobro en vuelo antes de empezar.
2. **El cajero no puede liberar un pedido desde la UI** (`pos_backend`): la app no tiene botón y
   la ficha del pedido le da `AccessError` sobre `stock.picking`. Sólo se libera al cerrar la caja.
3. **Un claim fallido se contesta como «no sé»** aunque no se haya posteado nada, y la
   disponibilidad no detecta un lock zombie del mismo origen. Menor: con el arreglo del lock, el
   zombie vence a los 2 minutos.
4. **El backend no tiene botón de cierre de lote**; en Campera lo cierra el POS Backend al cerrar
   la caja.
5. **`LocalizacionUy`: `numero_cfe()` no lee las facturas migradas de v17** (15.639 de 15.700). Ver
   `doc/dual-landing.md`, «Reportado».
6. **La URL del concentrador no se valida** (acepta `http://`). Verificar a mano en producción.

## Contingencia del día 1 — si Getnet falla en la caja

Para el cajero, en este orden. **Regla de oro: si hay duda de si la tarjeta se cobró, NO se vuelve
a pasar.** Un cobro que quizá existe se resuelve consultando, no cobrando dos veces.

### A · El cobro con Getnet dio error o quedó «SIN CONFIRMAR»

1. **No vuelvas a pasar la tarjeta.**
2. **Esperá: la pantalla consulta sola** («Esperando el pinpad…») hasta el tope del pinpad (3
   minutos). **Consultar** hace lo mismo al instante; no hace falta tocarlo.
3. Según lo que diga:
   - **Autorizado** → seguí normal y **Finalizá**.
   - **Descartado** (con el motivo de la terminal) → la tarjeta NO se cobró. Cobrá con otro medio.
   - **Sigue sin confirmar** («se sigue verificando solo») → tocá **Descartar**, cobrá con otro medio y **avisá al supervisor**
     con el número de pedido. El cobro queda anotado: si después resulta aprobado, el sistema lo
     **devuelve solo** (cron de cobros huérfanos) y aparece en *Contabilidad > Pagos > «Getnet:
     requieren conciliación»* si no lo pudo resolver.
4. Si el mensaje dice que la terminal está **ocupada por otra operación**, esperá un minuto y
   volvé a intentar; si persiste, avisá al supervisor.

### B · Getnet no anda para nadie (concentrador caído, pinpad sin conexión)

**Lo decide y lo hace el supervisor o quien tenga Ajustes, no el cajero:**

1. *Contabilidad > Configuración > Proveedores de pago* (o *Ajustes > Facturación > Proveedores de
   pago*) → **Getnet (TransAct)** → estado **Deshabilitado** → Guardar.
2. Efecto inmediato en **todas** las cajas: el medio *Getnet (pinpad)* aparece gris con el motivo
   «El proveedor Getnet de la terminal … está deshabilitado». Verificado contra el simulador.
3. Los cajeros cobran con los otros medios (efectivo, transferencia, y **tarjeta manual** si se
   configuró antes de salir — ver go-live, ítem 1.23 del go-live).
4. Cuando Getnet vuelve: mismo camino, estado **Habilitado**.

### C · Antes de cerrar la caja

- **Antes de cerrar, ningún cobro Getnet debería quedar «SIN CONFIRMAR».** Resolvelo con
  **Consultar** (A.2) o con **Descartar** (A.3). Desde la fase 1 cerrar ya no se cuelga (cada
  consulta dura segundos), pero la caja no cierra limpio con plata sin saber.
- El cierre de caja **cierra el lote de la terminal**. Si la terminal no contesta, la caja se cierra
  igual (con un Supervisor, que queda registrado) y el lote se cierra después.

### D · Promociones por tarjeta

- **«No se pudo leer la tarjeta… pasa a promociones manuales»**: si la tarjeta tiene promo, tocá
  «Getnet · <promo>» y cobrá; si no, tocá **Agregar** de nuevo y se cobra el total.
- **PROMO NO APLICADA**: **Seguir sin promo**, o **Reversar (DEV) y cobrar con promo** y volver a
  cobrar con la misma tarjeta.
- **PROMO NO COINCIDE**: **Reversar (DEV) y cobrar sin promo**, y cobrar el total.
- **Rechazada con la promo aplicada** y se va a pagar de otra forma: **Quitar promo** primero.
- **Si en una caja la lectura falla siempre**: un Manager POS la pasa a **Manual** (*Configuración
  › Cajas › la caja › Medios de pago › fila Getnet › Modo de promociones Getnet*). Rige desde el
  próximo cobro.

## Pendiente de publicar

> **Decisión de Daryl, 27/09/2026:** P3 y el backend se validan contra un **concentrador
> simulado** y se publica todo para el go-live de Campera (jueves 01/10/2026). La validación con
> hardware queda para el primer cobro real en producción. Lo que el simulador no pudo validar está
> en la sección «Validación». Este bloque se actualiza en cada entrega; **no se pushea nada sin
> que Daryl lo revise**.

Actualizado: 28/09/2026 — fase 1 + promociones (línea de descuento). La rama publicada no lleva evidencia binaria: los videos quedan en «Desarrollos Documentos/Getnet Campera».

**1. `pos_backend` de Campera** — dependencia de despliegue de P3 y de las promociones. Sobre
`origin @ cb4223f`: `b5cbea5` (hook 7 de cierre, liberación) → `4935540` [FIX] descuento global con
cobros confirmados → `b20023a` cobro automático → `927d4e0` Liberar para el cajero → `8b8356d`
operaciones opcionales 8 → `eb18622` recarga tras un cobro que no arrancó. Va primero.

    cd ~/Odoo/clients/campera/pos_backend && git push origin <sha de la punta>:refs/heads/19.0

**2. `retail-ecommerce` · `19.0_getnet`** — sobre `origin @ 1184177`, en este orden:
`[FIX]` DL-1b (`dd071b1`) → `[FIX]` módulos v17 no instalables (`4a35d91`) → `[FIX]` núcleo, lock
a nombre del token → `[FIX]` backend, polling como contador → `[FIX]` backend, facturas migradas de
v17 (error claro) → `[FIX]` estándar, facturas de v17 con su FacturaNro real → `[FIX]` núcleo, URL
sólo https → los `[DOC]` de estado → **`[ADD]` P3** (un solo commit, con la consulta corta y la
puesta al día de la línea) → los `[DOC]` de evidencia de la Parte A (guion, sin video) y de la validación con simulador
→ **`[ADD]` promociones** → este `[DOC]`.

    cd ~/Odoo/shared/primateuy/retail-ecommerce-19.0 && git push origin <sha de la punta>:refs/heads/19.0_getnet

El sha de la punta **no puede escribirse acá**: este archivo vive en un commit que está debajo, y
el sha de cualquier commit de arriba depende del de éste. El comando completo, con el sha, va en el
reporte de cada entrega.

**3. Puntero del submódulo en Campera** — **lo mueve Daryl a mano**, después del paso 2 y sólo a
un sha ya publicado en `19.0_getnet` (regla 3 de abajo). Quien entrega no lo commitea ni arma su
comando.

**No va en esta secuencia:**

- `17.0_getnet` — **congelado** (DL-1 `b3f2226` y DL-2 `0a60c7b` locales). v17 no tiene destino por
  ahora; se retoma después de Campera.
- `LocalizacionUy` @ `effbe0c` (botón «Restablecer a borrador», `19.0_staging`) — módulo
  compartido, afecta a todos los proyectos: decisión aparte.

      cd ~/Odoo/shared/primateuy/LocalizacionUy-19.0 && git push origin effbe0c6a3fd37eb496e48f8fba96ac5222001ea:refs/heads/19.0_staging

## Convenciones de push

Los pushes los corre Daryl. Quien entrega deja el comando **armado**, listo para copiar:

    cd <ruta absoluta del repo> && git push origin <sha completo>:refs/heads/<rama>

1. **Siempre con sha explícito y `refs/heads/<rama>`.** Nunca `git push` a secas desde este
   worktree: la rama local `19.0_getnet` lleva encima el trabajo en curso (P3, evidencia) y un
   push sin refspec lo publica entero como fast-forward. Eso fue exactamente el incidente de abajo.
2. **Siempre con `cd` explícito en la misma línea.** El sha corto de un repo no existe en otro;
   correr el comando en el directorio equivocado falla o, peor, publica otra cosa.
3. **El puntero del submódulo en Campera sólo apunta a commits publicados en `19.0_getnet`.**
   Nada local, nada que pueda desaparecer con una reversión.
4. **Orden dependiente-primero cuando hay submódulo.** Si una reversión o reescritura de
   `19.0_getnet` deja fuera un commit al que apunta Campera, primero se mueve y publica el
   puntero de Campera, después se reescribe `19.0_getnet`. Nunca al revés.

**Guard mecánico.** `push.default = nothing` está configurado con `--local` en el repo de
retail-ecommerce (config compartida: vale para este worktree y para el clon de v17) y en el
clon de Campera. Un `git push` sin refspec falla con
`fatal: You didn't specify any refspecs to push, and push.default is "nothing".`
El comando con `sha:refs/heads/<rama>` sigue funcionando (verificado con `--dry-run` el
27/09/2026 en los dos repos: `Everything up-to-date`). Es configuración local, no viaja con el
repo: en un clon nuevo hay que volver a ponerla.

## Incidente de publicación — 27/09/2026

- **15:29:30** — un `git push` sin refspec desde este worktree publicó `19.0_getnet` hasta
  `2bde13e`: 8 commits sobre `2371fb1` en lugar de 2. De más: los 4 de P3
  (`7cc86d8`, `8a723e1`, `c8a5f86`, `2fa33e5`) y los 2 de evidencia (`a865bd7`, `2bde13e`),
  incluido el video de la Parte A. P3 no estaba validado con hardware.
- **15:33:32** — Campera commiteó y publicó el puntero del submódulo en `2bde13e`
  (`869b9b1` en `staging.27.08.2026v2`).
- **entre 16:00:00 y 16:03:58** (ls-remote antes y después) — reversión: `git push --force-with-lease=19.0_getnet:2bde13e origin
  1184177:19.0_getnet` desde este worktree. Quedó `origin/19.0_getnet @ 1184177`
  ([ADD] `a740ddd` + [FIX] `1184177`), sin archivos de P3 ni de evidencia. Un primer
  intento desde el clon de Campera falló sin tocar nada (el sha no existe en ese repo).
- **Consecuencia de hacerlo en ese orden:** Campera quedó apuntando a un sha que ninguna rama
  contenía. Se corrigió con `0339edb` («[FIX] Submódulo retail-ecommerce vuelve a 1184177 (P3
  no validado)»), publicado en `staging.27.08.2026v2` y verificado a las 16:09.
- **Nada se perdió.** Los 6 commits siguen en la rama local `19.0_getnet`,
  en `respaldo-getnet-v19-2026-09-27-b @ 2bde13e` de este repo y en
  `respaldo-p3-2bde13e-2026-09-27` del submódulo de Campera. La `19.0_getnet` local del
  submódulo quedó en `1184177` siguiendo a origin.
- **Qué se cambió para que no se repita:** las cuatro reglas y el guard de arriba.
