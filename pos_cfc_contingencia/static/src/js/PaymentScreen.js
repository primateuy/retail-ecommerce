/** @odoo-module **/
/*
 * pos_cfc_contingencia — patch de PaymentScreen.
 *
 * Funcionalidad:
 *   1. Al montar la pantalla, consulta el RPC `pos.session.cfc_cae_info` para
 *      determinar si el PDV opera en modo contingencia y, si es así, cargar
 *      los datos del CAE activo (banner).
 *   2. En `validateOrder`, exige y valida el folio del talonario ANTES de
 *      dejar seguir. Si falta, lo pide con su propio popup.
 *
 * Por qué en `validateOrder` y no en `_finalizeValidation`
 * -------------------------------------------------------
 * `validateOrder` del core borra las líneas de pago pendientes JUSTO ANTES de
 * llamar a `_finalizeValidation`:
 *
 *     if (await this._isOrderValid(isForceValidate)) {
 *         // remove pending payments before finalizing the validation
 *         for (const line of this.paymentLines) {
 *             if (!line.is_done()) { this.currentOrder.remove_paymentline(line); }
 *         }
 *         await this._finalizeValidation();
 *     }
 *
 * Una versión anterior validaba adentro de `_finalizeValidation`: al rechazar,
 * la orden ya se había quedado sin pagos, el botón Validar pasaba a `disabled`
 * —depende de `is_paid()`— y el cajero quedaba trabado sin forma de reintentar.
 * Toda validación que pueda rechazar tiene que correr antes del super.
 *
 * Por qué el folio no se lee de `pos_reference_for_payment`
 * --------------------------------------------------------
 * Antes se leía de `this.state.code`, que ese módulo llena en el handler de su
 * botón "Payment Reference". Ese botón solo se renderiza si está activo el
 * ajuste `is_allow_payment_ref`: con el ajuste apagado no había manera de
 * cargar el folio y el PDV pedía un dato que la pantalla no dejaba ingresar.
 * Además ese estado vive en el componente y no se limpia entre órdenes, así que
 * el folio de una venta podía colarse en la siguiente y duplicar el número del
 * talonario.
 *
 * Acá el folio se guarda en la orden (`cfc_folio`), viaja con ella en
 * `export_as_JSON` y muere con ella. `this.state.code` se sigue aceptando como
 * valor inicial, para no cambiarle la costumbre a quien ya usa ese botón.
 *
 * Si es contingencia no depende del RPC
 * -------------------------------------
 * `pos.config.cfc_es_contingencia` llega con la carga del POS. Antes la única
 * fuente era `cfc_cae_info`, y el `catch` se tragaba su error: un cajero sin
 * permiso sobre `cae.contingencia` recibía AccessError, el PDV se comportaba
 * como uno común, no pedía folio y el backend rechazaba la factura. Si el RPC
 * falla en un PDV de contingencia, el folio se pide igual y el rango lo
 * controla el backend al sincronizar.
 */
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { ErrorPopup } from "@point_of_sale/app/errors/popups/error_popup";
import { TextInputPopup } from "@point_of_sale/app/utils/input_popups/text_input_popup";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";
import { useState, onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

patch(PaymentScreen.prototype, {
    setup() {
        super.setup();
        this.cfcOrm = useService("orm");
        this.cfcPopup = useService("popup");
        this.cfcState = useState({
            isCfc: false,
            hasCae: false,
            envioOnline: false,
            nroCae: "",
            fechaVencimiento: null,
            rangoInicial: 0,
            rangoFinal: 0,
            foliosDisponibles: 0,
            warningVencimiento: false,
            // El PDV es de contingencia pero no se pudieron traer los datos del CAE.
            caeNoDisponible: false,
            loaded: false,
        });
        onWillStart(async () => {
            await this._cfcCargarDatosCAE();
        });
    },

    async _cfcCargarDatosCAE() {
        this.cfcState.isCfc = !!this.pos.config.cfc_es_contingencia;
        try {
            const info = await this.cfcOrm.call(
                "pos.session",
                "cfc_cae_info",
                // En 17 la sesión del store es `pos_session`; `this.pos.session` no
                // existe y este RPC fallaba siempre en silencio.
                [[this.pos.pos_session.id]],
            );
            if (!info || !info.is_cfc) {
                this.cfcState.isCfc = false;
                this.cfcState.loaded = true;
                return;
            }
            this.cfcState.isCfc = true;
            this.cfcState.envioOnline = !!info.envio_online;
            if (info.has_cae) {
                this.cfcState.hasCae = true;
                this.cfcState.nroCae = info.nro_cae;
                this.cfcState.fechaVencimiento = info.fecha_vencimiento;
                this.cfcState.rangoInicial = info.rango_inicial;
                this.cfcState.rangoFinal = info.rango_final;
                this.cfcState.foliosDisponibles = info.folios_disponibles;
                // Aviso si vence en menos de 30 días.
                const hoy = new Date();
                const venc = new Date(info.fecha_vencimiento);
                const diasRestantes = Math.floor((venc - hoy) / 86400000);
                this.cfcState.warningVencimiento = diasRestantes < 30;
            }
        } catch (e) {
            // No interrumpir la operativa si el RPC falla, pero si el PDV es de
            // contingencia el folio se sigue pidiendo (ver `_cfcControlPrevio`).
            console.error("[CFC] No se pudo cargar datos del CAE:", e);
            this.cfcState.caeNoDisponible = this.cfcState.isCfc;
        } finally {
            this.cfcState.loaded = true;
        }
    },

    /**
     * Folio ya asociado a la orden en curso. Si todavía no hay ninguno, se
     * acepta como valor inicial el del botón "Payment Reference" de
     * `pos_reference_for_payment`, para quien lo tenga habilitado y lo use.
     */
    _cfcObtenerFolio() {
        const orden = this.currentOrder;
        if (orden && orden.cfc_folio) {
            return String(orden.cfc_folio).trim();
        }
        return (this.state && this.state.code) ? String(this.state.code).trim() : "";
    },

    /**
     * Devuelve un mensaje de error (string) o null si el folio es válido.
     * Replica las validaciones del backend `cae.contingencia.validar_folio`
     * (excepto duplicado, que se delega al backend por volumen de datos).
     * Sin datos del CAE solo se controla que haya un número entero.
     */
    _cfcValidarFolio(folio) {
        if (!folio) {
            return _t("Debe ingresar el número de folio del talonario de contingencia.");
        }
        const n = parseInt(folio, 10);
        if (isNaN(n) || String(n) !== folio) {
            return _t("El folio debe ser un número entero.");
        }
        if (!this.cfcState.hasCae) {
            return null;
        }
        if (this.cfcState.fechaVencimiento) {
            const hoy = new Date();
            hoy.setHours(0, 0, 0, 0);
            const venc = new Date(this.cfcState.fechaVencimiento);
            if (venc < hoy) {
                return _t("El CAE de contingencia está vencido (venció el %s). Contacte al administrador.")
                    .replace("%s", this.cfcState.fechaVencimiento);
            }
        }
        if (n < this.cfcState.rangoInicial || n > this.cfcState.rangoFinal) {
            return _t("El folio %(n)s está fuera del rango autorizado (%(ini)s - %(fin)s).")
                .replace("%(n)s", n)
                .replace("%(ini)s", this.cfcState.rangoInicial)
                .replace("%(fin)s", this.cfcState.rangoFinal);
        }
        return null;
    },

    /**
     * Pide el folio al cajero y lo deja en la orden. Devuelve true si quedó
     * uno válido, false si canceló o si lo ingresado no pasa la validación.
     *
     * No se depende del botón de `pos_reference_for_payment`: en un PDV de
     * contingencia el folio es obligatorio, así que la pantalla lo pide sola.
     */
    async _cfcPedirFolio() {
        const sugerido = this._cfcObtenerFolio();
        // `TextInputPopup` del core solo dibuja título, input y placeholder (no
        // `body`), así que el rango va en el título.
        const title = this.cfcState.hasCae
            ? _t("Folio del talonario de contingencia (rango %(ini)s - %(fin)s)")
                .replace("%(ini)s", this.cfcState.rangoInicial)
                .replace("%(fin)s", this.cfcState.rangoFinal)
            : _t("Folio del talonario de contingencia (el rango se controla al sincronizar)");
        const { confirmed, payload } = await this.cfcPopup.add(TextInputPopup, {
            title,
            startingValue: sugerido,
            placeholder: String(this.cfcState.rangoInicial || ""),
        });
        if (!confirmed) {
            return false;
        }
        const folio = String(payload || "").trim();
        const err = this._cfcValidarFolio(folio);
        if (err) {
            await this.cfcPopup.add(ErrorPopup, {
                title: _t("Folio inválido"),
                body: err,
            });
            return false;
        }
        this.currentOrder.cfc_folio = folio;
        return true;
    },

    /**
     * Control del folio ANTES de que el core toque la orden. Devuelve true si
     * se puede seguir con la validación.
     */
    async _cfcControlPrevio() {
        if (!this.cfcState.isCfc) {
            return true;
        }
        if (!this.cfcState.hasCae && !this.cfcState.caeNoDisponible) {
            await this.cfcPopup.add(ErrorPopup, {
                title: _t("PDV de Contingencia sin CAE"),
                body: _t("No hay un CAE de contingencia activo configurado para este diario. Contacte al administrador."),
            });
            return false;
        }
        const folio = this._cfcObtenerFolio();
        if (this._cfcValidarFolio(folio)) {
            // Falta o no sirve: se pide en el momento en vez de rechazar a secas.
            return await this._cfcPedirFolio();
        }
        this.currentOrder.cfc_folio = folio;
        return true;
    },

    async validateOrder(isForceValidate) {
        if (!(await this._cfcControlPrevio())) {
            return;
        }
        return super.validateOrder(...arguments);
    },
});
