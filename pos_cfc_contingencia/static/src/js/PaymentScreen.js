/** @odoo-module **/
/*
 * pos_cfc_contingencia — patch de PaymentScreen.
 *
 * Funcionalidad:
 *   1. Al montar la pantalla, consulta el RPC `pos.session.cfc_cae_info` para
 *      determinar si el PDV opera en modo contingencia y, si es así, cargar
 *      los datos del CAE activo (banner).
 *   2. En `_finalizeValidation`, valida el folio ingresado por el cajero
 *      (en el popup de `pos_reference_for_payment`) ANTES de procesar el pago.
 *      Si falla, bloquea con un ErrorPopup y NO confirma la orden.
 *
 * Dependencia clave: `pos_reference_for_payment` guarda el folio ingresado por
 * el cajero en `this.state.code` de la instancia patch. Como nuestro módulo
 * depende de él, su patch corre antes en setup() y `this.state.code` queda
 * disponible cuando este patch lo lee.
 */
import { PaymentScreen } from "@point_of_sale/app/screens/payment_screen/payment_screen";
import { ErrorPopup } from "@point_of_sale/app/errors/popups/error_popup";
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
            loaded: false,
        });
        onWillStart(async () => {
            await this._cfcCargarDatosCAE();
        });
    },

    async _cfcCargarDatosCAE() {
        try {
            const info = await this.cfcOrm.call(
                "pos.session",
                "cfc_cae_info",
                [[this.pos.session.id]],
            );
            if (!info || !info.is_cfc) {
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
            // No interrumpir la operativa si el RPC falla; logueamos en consola.
            console.error("[CFC] No se pudo cargar datos del CAE:", e);
        } finally {
            this.cfcState.loaded = true;
        }
    },

    /**
     * Lee el folio ingresado por el cajero. Lo provee `pos_reference_for_payment`
     * en `this.state.code` (después de que el popup confirma).
     */
    _cfcObtenerFolio() {
        return (this.state && this.state.code) ? String(this.state.code).trim() : "";
    },

    /**
     * Devuelve un mensaje de error (string) o null si el folio es válido.
     * Replica las validaciones del backend `cae.contingencia.validar_folio`
     * (excepto duplicado, que se delega al backend por volumen de datos).
     */
    _cfcValidarFolio(folio) {
        if (!folio) {
            return _t("Debe ingresar el número de folio del talonario de contingencia.");
        }
        const n = parseInt(folio, 10);
        if (isNaN(n) || String(n) !== folio) {
            return _t("El folio debe ser un número entero.");
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

    async _finalizeValidation() {
        if (!this.cfcState.isCfc) {
            return super._finalizeValidation(...arguments);
        }
        if (!this.cfcState.hasCae) {
            await this.cfcPopup.add(ErrorPopup, {
                title: _t("PDV de Contingencia sin CAE"),
                body: _t("No hay un CAE de contingencia activo configurado para este diario. Contacte al administrador."),
            });
            return;
        }
        const folio = this._cfcObtenerFolio();
        const err = this._cfcValidarFolio(folio);
        if (err) {
            await this.cfcPopup.add(ErrorPopup, {
                title: _t("Folio inválido"),
                body: err,
            });
            return;
        }
        return super._finalizeValidation(...arguments);
    },
});
