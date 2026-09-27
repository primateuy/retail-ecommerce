# Getnet / TransAct en Odoo 19 — estado de la rama

Rama `19.0_getnet`. Port de la integración Getnet/TransAct desde `17.0_getnet @ 2371fb1`.

## Qué entra en esta entrega

| módulo | qué es |
|---|---|
| `odoo_pos_getnet_core` | proveedor, terminal con lock entre flujos, transacción, motor de polling, cliente SOAP, cron de recuperación, cierre de lote |
| `odoo_pos_getnet_backend` | el flujo contable: cobrar y devolver desde **Contabilidad > Pagos** |

## Suites

Medido en `o19_getnet_test` (v19, con `l10n_uy_einvoice_base` y `l10n_uy_einvoice_uruware`
instalados y todo endpoint en modo testing):

| suite | resultado |
|---|---|
| `odoo_pos_getnet_core` | **58 / 58** |
| `odoo_pos_getnet_backend` | **37 / 37** |
| las dos juntas | **95 / 95** |

```bash
odoo-bin -c <conf> -d o19_getnet_test -u odoo_pos_getnet_core,odoo_pos_getnet_backend \
  --test-enable --test-tags /odoo_pos_getnet_core,/odoo_pos_getnet_backend \
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

- **Puente con Fiserv** (`odoo_pos_getnet_fiserv_flags`): fuera de esta entrega.
- **Botón en la factura**: el camino soportado es Contabilidad > Pagos. El wizard «Registrar pago»
  de la factura no sirve para este flujo y no es un defecto.
- **Refresco automático del form del pago**: hay que refrescar a mano. Backlog conocido, está
  documentado en la guía de usuario sin disimulo.
- **Validación con pinpad**: pendiente de agenda. El smoke contra el concentrador de integración
  del 26/09/2026 no se pudo completar porque el concentrador devolvía 502/504 — ver `smoke_v19.md`.

## Trabajo en curso, fuera de la entrega

`odoo_pos_getnet_pos_backend` —la terminal Getnet para el **POS Backend** de campera (Sprint 12)—
va en commits propios **encima** de la entrega. No forma parte del `[ADD]`.

## Pendiente de publicar

> **Decisión de Daryl, 27/09/2026:** P3 y el backend se validan contra un **concentrador
> simulado** y se publica todo para el go-live de Campera (jueves 01/10/2026). La validación con
> hardware queda para el primer cobro real en producción. Lo que el simulador no pudo validar está
> en la sección «Validación». Este bloque se actualiza en cada entrega; **no se pushea nada sin
> que Daryl lo revise**.

Actualizado: 27/09/2026 — entrega de validación con simulador.

**1. `pos_backend` de Campera** — dependencia de despliegue de P3 (hook 7 de cierre, arreglo de
liberación, texto del contrato). Va primero: P3 publicado sin esto no cierra.

    cd ~/Odoo/clients/campera/pos_backend && git push origin b5cbea59ea975e020d2ea331d9d20ed72daa18f7:refs/heads/19.0

**2. `retail-ecommerce` · `19.0_getnet`** — sobre `origin @ 1184177`, en este orden:
`[FIX]` DL-1b (`dd071b1`) → `[FIX]` módulos v17 no instalables (`4a35d91`) → `[FIX]` núcleo, lock
a nombre del token (`3a17e8d`) → `[FIX]` backend, polling como contador (`71d364a`) → `[FIX]` backend, facturas migradas de v17 (`41cbd38`) → los `[DOC]` de estado → **`[ADD]` P3** (un solo commit) → los
`[DOC]` de evidencia de la Parte A y de la validación con simulador.

    cd ~/Odoo/shared/primateuy/retail-ecommerce-19.0 && git push origin <sha de la punta>:refs/heads/19.0_getnet

El sha de la punta **no puede escribirse acá**: este archivo vive en un commit que está debajo, y
el sha de cualquier commit de arriba depende del de éste. El comando completo, con el sha, va en el
reporte de cada entrega.

**3. Puntero del submódulo en Campera** — **después** del paso 2 y sólo a un sha ya publicado en
`19.0_getnet` (regla 3 de abajo). Se commitea al momento y el comando se arma con ese sha. La rama
es la del entorno donde se despliega (hoy staging: `staging.27.08.2026v2`; la de producción v19 la
define Daryl):

    cd ~/Odoo/clients/campera && git push origin <sha del commit del puntero>:refs/heads/<rama de Campera>

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
