/** @odoo-module */

import { _t } from "@web/core/l10n/translation";
import { ErrorPopup } from "@point_of_sale/app/errors/popups/error_popup";
import { PartnerDetailsEdit } from "@point_of_sale/app/screens/partner_list/partner_editor/partner_editor";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { useState } from "@odoo/owl";

// Forzar uso del template personalizado del modulo
PartnerDetailsEdit.template = "pos_forum_customer_ui.PartnerDetailsEdit";

patch(PartnerDetailsEdit.prototype, {
    setup() {
        // Ejecutar la inicializacion base del editor
        super.setup(...arguments);

        // Servicios requeridos para validaciones y llamadas al backend
        this.orm = useService("orm");
        this.popup = useService("popup");

        // Estado UI exclusivo del formulario (no se persiste en el partner)
        // Auto-marcar si el partner ya existe y no tiene email registrado
        const partner = this.props.partner;
        this.uiState = useState({
            no_tiene_mail: Boolean(partner.id) && !partner.email,
        });
        this.changes.is_company = Boolean(partner.is_company);
        this.changes.company_type = partner.company_type || (partner.is_company ? "company" : "person");
        this.changes.l10n_latam_identification_type_id =
            partner.l10n_latam_identification_type_id &&
            partner.l10n_latam_identification_type_id[0];
        this.changes.birthdate_date = partner.birthdate_date || false;
        this.changes.social_reason = partner.social_reason || false;

        // Asegurar conversion correcta de IDs enteros
        if (!this.intFields.includes("l10n_latam_identification_type_id")) {
            this.intFields.push("l10n_latam_identification_type_id");
        }

        // Asegurar nombres de persona cuando partner_firstname esta disponible
        if (this.partnerFirstnameEnabled) {
            if (this.changes.firstname === undefined) {
                this.changes.firstname = partner.firstname || false;
            }
            if (this.changes.lastname === undefined) {
                this.changes.lastname = partner.lastname || false;
            }
        }

        // Inicializar genero cuando partner_gender esta disponible
        if (this.partnerGenderEnabled && this.changes.gender === undefined) {
            this.changes.gender = partner.gender || false;
        }

        // Aplicar valores por defecto para calle y ciudad cuando corresponde
        this._applyDefaultAddressValues();

        // Guardar pais actual para detectar cambio de pais y prefijo telefonico
        this._previousCountryId = this.changes.country_id;
        // Si hay pais, asegurar que telefono/celular tengan prefijo con codigo de pais
        this._applyCountryCodeToPhones();
    },

    _applyDefaultAddressValues() {
        // Si ya hay datos, no sobreescribir
        if (!this.changes.street) {
            this.changes.street = this.pos.config.default_partner_street || false;
        }
        if (!this.changes.city) {
            this.changes.city = this.pos.config.default_partner_city || false;
        }
        // Many2one llega del backend como [id, display_name] o como número segun version
        if (!this.changes.country_id) {
            const c = this.pos.config.default_partner_country_id;
            this.changes.country_id = (Array.isArray(c) ? c[0] : c) || false;
        }
        if (!this.changes.state_id) {
            const s = this.pos.config.default_partner_state_id;
            this.changes.state_id = (Array.isArray(s) ? s[0] : s) || false;
        }
    },

    toggleIsCompany() {
        // Alternar tipo de cliente entre persona y empresa
        this.changes.is_company = !this.changes.is_company;
        this.changes.company_type = this.changes.is_company ? "company" : "person";
    },

    get partnerFirstnameEnabled() {
        // Definir si el POS debe usar firstname/lastname
        return Boolean(this.pos.partner_firstname_enabled);
    },

    get partnerGenderEnabled() {
        return Boolean(this.pos.partner_gender_enabled);
    },

    /**
     * Tipos de documento disponibles en el POS filtrados por tipo de contacto.
     *
     * El campo ``company_type`` de l10n_latam.identification.type (definido en
     * l10n_uy_einvoice_base) toma 'person', 'company' o 'both'. Personas ven
     * los tipos con company_type 'person' o 'both'; empresas ven los 'company'
     * o 'both'. Los tipos con company_type vacio/null se tratan como 'both' para
     * no esconder configuraciones heredadas que aun no clasificaron sus docs.
     */
    get identificationTypes() {
        const allTypes = this.pos.identification_types || [];
        const targetType = this.changes.is_company ? "company" : "person";
        return allTypes.filter((doc) => {
            const type = doc.company_type || "both";
            return type === targetType || type === "both";
        });
    },

    /**
     * Codigo de pais con + para prefijo telefonico (ej. +598).
     * Se usa al cargar el formulario y al cambiar pais.
     */
    get countryPhoneCode() {
        const country = this.pos.countries?.find((c) => c.id === this.changes.country_id);
        const code = country?.phone_code;
        if (code != null && code !== false && code !== "") {
            return "+" + String(code);
        }
        return "";
    },

    /**
     * Muestra el boton Consultar RUT solo cuando el tipo de documento
     * seleccionado es RUT/RUC (mismas condiciones que en backend).
     * En Uruguay el tipo es "RUC" (code "2"); en otras localizaciones puede ser "it_rut".
     * code en l10n_latam puede ser numero o string, por eso se fuerza a string.
     */
    get showConsultRutButton() {
        const typeId = this.changes.l10n_latam_identification_type_id;
        if (!typeId) {
            return false;
        }
        const idKey = typeof typeId === "number" ? typeId : parseInt(typeId, 10);
        const docType = this.pos.identification_type_by_id?.[idKey];
        if (!docType) {
            return false;
        }
        const code = String(docType.code ?? "").toLowerCase().trim();
        const name = String(docType.name ?? "").toLowerCase().trim();
        return (
            code === "it_rut" ||
            code === "2" ||
            name.includes("rut") ||
            name.includes("ruc")
        );
    },

    get mobilePlaceholder() {
        // Placeholder de celular con codigo de pais cuando esta definido (ej. +598 09x xxx xxx)
        const country = this.pos.countries?.find((c) => c.id === this.changes.country_id);
        const format = country?.pos_phone_format || "09x xxx xxx";
        const prefix = this.countryPhoneCode;
        if (prefix) {
            return `${prefix} ${format}`;
        }
        return format;
    },

    get phonePlaceholder() {
        // Placeholder de telefono SIN prefijo de pais; solo el formato nacional
        const country = this.pos.countries?.find((c) => c.id === this.changes.country_id);
        return country?.pos_phone_format || "09x xxx xxx";
    },

    get mobileLabel() {
        // Construir etiqueta dinamica para celular segun el formato del pais
        const country = this.pos.countries?.find((c) => c.id === this.changes.country_id);
        if (country && country.pos_phone_format) {
            return `${_t("Celular")} - ${country.pos_phone_format}`;
        }
        return _t("Celular");
    },

    get phoneLabel() {
        // Construir etiqueta dinamica para telefono segun el formato del pais
        const country = this.pos.countries?.find((c) => c.id === this.changes.country_id);
        if (country && country.pos_phone_format) {
            return `${_t("Telefono")}`;
        }
        return _t("Telefono");
    },

    onVatChange() {
        // Para RUT/RUC la consulta DGI es la validacion autoritativa; no validar
        // aqui para evitar el doble popup al perder foco al presionar el boton.
        if (this.showConsultRutButton) {
            return;
        }
        this._validateVatValue(this.changes.vat);
    },

    onMobileChange() {
        // Validar celular al modificar el campo
        this._validatePhoneValue(this.changes.mobile, _t("Celular"));
    },

    onPhoneChange() {
        // Validar telefono al modificar el campo
        this._validatePhoneValue(this.changes.phone, _t("Telefono"));
    },

    /**
     * Al cambiar el pais, actualizar prefijo de telefono/celular al nuevo codigo
     * (comportamiento igual al backend).
     * Se lee el nuevo pais desde ev.target.value porque t-model puede aun no
     * haber actualizado this.changes.country_id cuando se dispara el evento.
     */
    onCountryChange(ev) {
        // Leer nuevo pais del evento; si no hay evento, usar el ya actualizado en changes
        const rawNew =
            ev?.target?.value !== undefined && ev?.target?.value !== ""
                ? ev.target.value
                : this.changes.country_id;
        const newCountryId = rawNew != null ? parseInt(String(rawNew), 10) : null;
        const oldCountryId = this._previousCountryId;
        this._previousCountryId = newCountryId;

        const oldCountry = this.pos.countries?.find((c) => c.id === oldCountryId);
        const newCountry = this.pos.countries?.find((c) => c.id === newCountryId);
        const oldCode = oldCountry?.phone_code != null ? String(oldCountry.phone_code) : "";
        const newCode = newCountry?.phone_code != null ? String(newCountry.phone_code) : "";
        const newPrefix = newCode ? "+" + newCode : "";

        const updatePhoneWithNewPrefix = (value) => {
            if (!value) {
                return newPrefix;
            }
            const digits = (value || "").replace(/\D/g, "");
            if (!digits) {
                return newPrefix;
            }
            // Quitar codigo del pais anterior si estaba al inicio
            let national = digits;
            if (oldCode && digits.startsWith(oldCode)) {
                national = digits.slice(oldCode.length);
            }
            return newPrefix ? newPrefix + national : national;
        };

        const newMobile = updatePhoneWithNewPrefix(this.changes.mobile);
        this.changes.mobile = newMobile;
    },

    /**
     * Al cargar el formulario: si hay pais con codigo, prefijar telefono/celular
     * con +codigo (ej. +598) cuando esten vacios o no tengan ya el prefijo.
     */
    _applyCountryCodeToPhones() {
        const prefix = this.countryPhoneCode;
        if (!prefix) {
            return;
        }
        // Aplicar prefijo solo al campo de celular (mobile)
        const field = "mobile";
        const value = this.changes[field];
        if (value == null || value === false || value === "") {
            this.changes[field] = prefix;
            return;
        }
        const digits = String(value).replace(/\D/g, "");
        if (!digits) {
            this.changes[field] = prefix;
            return;
        }
        const code = prefix.replace("+", "");
        if (!digits.startsWith(code)) {
            this.changes[field] = prefix + digits;
        }
    },

    /**
     * Valida que la parte nacional del telefono tenga exactamente 8 digitos.
     * Retorna true si es valido, false si es invalido (y muestra popup).
     */
    _validatePhoneValue(value, label) {
        if (!value || (value || "").trim() === "") {
            return true;
        }
        const country = this.pos.countries?.find((c) => c.id === this.changes.country_id);
        const phoneCode = country?.phone_code != null ? String(country.phone_code) : "";
        const digitsOnly = (value || "").replace(/\D/g, "");
        const nationalDigits = phoneCode && digitsOnly.startsWith(phoneCode)
            ? digitsOnly.slice(phoneCode.length)
            : digitsOnly;
        if (nationalDigits.length !== 8) {
            this._showValidationError(
                _t("Invalid Phone"),
                _t("%s must be 8 digits.", label)
            );
            return false;
        }
        return true;
    },

    async _validateVatValue(vatValue) {
        // Validar numero de documento al modificar
        if (!vatValue) {
            this._showValidationError(
                _t("Invalid Document"),
                _t("Document number is required.")
            );
            return;
        }
        const typeId = this.changes.l10n_latam_identification_type_id;
        if (!typeId) {
            return;
        }
        const docType = this.pos.identification_type_by_id?.[typeId];
        if (!docType || !docType.check_number) {
            return;
        }
        if (docType.check_type === "ci") {
            const isValid = this._validateCi(vatValue);
            if (!isValid) {
                this._showValidationError(
                    _t("Invalid Document"),
                    _t("The document number is invalid for this type.")
                );
            }
            return;
        }
        try {
            await this.orm.call("l10n_latam.identification.type", "check_valid_number", [
                [typeId],
                vatValue,
            ]);
        } catch (error) {
            this._showValidationError(
                _t("Invalid Document"),
                _t("The document number is invalid for this type.")
            );
        }
    },

    _validateCi(ciValue) {
        // Validar CI con digito verificador (Uruguay)
        const digits = String(ciValue || "").replace(/\D/g, "");
        if (!digits || digits.length < 2) {
            return false;
        }
        const padded = digits.padStart(7, "0");
        const body = padded.slice(0, -1);
        const checkDigit = parseInt(padded.slice(-1), 10);
        const weights = "2987634";
        let acc = 0;
        for (let i = 0; i < weights.length; i++) {
            acc += (parseInt(weights[i], 10) * parseInt(body[i], 10)) % 10;
        }
        const expected = acc % 10 === 0 ? 0 : 10 - (acc % 10);
        return checkDigit === expected;
    },

    _showValidationError(title, body) {
        // Mostrar popup de validacion
        this.popup.add(ErrorPopup, { title, body });
    },

    async consultRut() {
        // Validar que exista numero de documento
        if (!this.changes.vat) {
            this.popup.add(ErrorPopup, {
                title: _t("RUT Query"),
                body: _t("Document number is required to consult RUT."),
            });
            return;
        }

        // Ejecutar la consulta DGI llamando al mismo metodo que se ejecuta en
        // backend (``get_partner_dgi_data`` de l10n_uy_einvoice_uruware) via
        // los wrappers ``pos_consultar_rut`` / ``pos_consultar_rut_preview``.
        const identTypeId = this.changes.l10n_latam_identification_type_id || false;

        let data = false;
        try {
            if (this.props.partner.id) {
                // Partner existente: actualiza el registro y devuelve campos.
                // Se pasa el tipo de identificacion seleccionado en el formulario
                // para que DGI valide contra el tipo correcto y no el de la BD.
                data = await this.orm.call("res.partner", "pos_consultar_rut", [
                    this.props.partner.id,
                    identTypeId,
                ]);
            } else {
                // Alta de cliente: el backend ejecuta la consulta DGI sobre un
                // partner temporal que se revierte (savepoint) y devuelve solo
                // los campos, sin id. El partner real se crea una unica vez al
                // guardar el formulario; consultar y cancelar no persiste nada.
                data = await this.orm.call("res.partner", "pos_consultar_rut_preview", [
                    this.changes.vat,
                    identTypeId,
                ]);
            }
        } catch (error) {
            // Mostrar el error tal cual viene de DGI/backend
            const message =
                error?.data?.message || error?.message || _t("Unknown error.");
            this.popup.add(ErrorPopup, {
                title: _t("RUT Query"),
                body: message,
            });
            return;
        }

        // Volcar la respuesta DGI al formulario del POS
        this._applyRutData(data);
    },

    _applyRutData(data) {
        // Actualizar valores del formulario con la respuesta del backend
        if (!data) {
            return;
        }
        this.changes.name = data.name || this.changes.name;
        this.changes.social_reason = data.social_reason || this.changes.social_reason;
        this.changes.street = data.street || this.changes.street;
        this.changes.street2 = data.street2 || this.changes.street2;
        this.changes.city = data.city || this.changes.city;
        // Preservar valores existentes si DGI no los devuelve (no pisar con false)
        this.changes.state_id = (data.state_id && data.state_id[0]) || this.changes.state_id;
        this.changes.country_id = (data.country_id && data.country_id[0]) || this.changes.country_id;
        // Si DGI dejo state pero no country, inferir country desde el state
        // (Uruware no setea country_id; el state apunta al res.country.state de UY)
        if (this.changes.state_id && !this.changes.country_id) {
            const state = this.pos.states?.find((s) => s.id === this.changes.state_id);
            if (state?.country_id) {
                this.changes.country_id = state.country_id[0];
            }
        }
        this.changes.zip = data.zip || this.changes.zip;
        this.changes.phone = data.phone || this.changes.phone;
        this.changes.mobile = data.mobile || this.changes.mobile;
        this.changes.email = data.email || this.changes.email;
        this.changes.vat = data.vat || this.changes.vat;
        // Uruware fuerza is_company=True para consultas de RUC; el template OWL
        // reacciona y conmuta entre seccion PERSONA y EMPRESA automaticamente.
        this.changes.is_company = Boolean(data.is_company);
        this.changes.company_type = data.company_type || this.changes.company_type;
    },

    toggleNoTieneMail() {
        this.uiState.no_tiene_mail = !this.uiState.no_tiene_mail;
        if (this.uiState.no_tiene_mail) {
            this.changes.email = false;
        }
    },

    _validateEmailFormat(email) {
        // Regex equivalente al email_re de Odoo (RFC 5322 simplificado)
        const emailRegex = /^[^\s@"(),:;<>[\\\]]+@[^\s@"(),:;<>[\\\]]+\.[a-zA-Z]{2,}$/;
        return emailRegex.test(email);
    },

    saveChanges() {
        // Si partner_firstname no esta disponible, evitar enviar campos inexistentes
        if (!this.partnerFirstnameEnabled) {
            delete this.changes.firstname;
            delete this.changes.lastname;
        }

        // Si es empresa, limpiar nombres y genero de persona
        if (this.partnerFirstnameEnabled && this.changes.is_company) {
            delete this.changes.firstname;
            delete this.changes.lastname;
        }
        if (this.partnerGenderEnabled && this.changes.is_company) {
            delete this.changes.gender;
        }

        // Validar telefono y celular antes de guardar (muestra popup si estan mal)
        if (this.changes.company_type === "person") {
            if (!this._validatePhoneValue(this.changes.mobile, _t("Celular"))) {
                return;
            }
            if (!this._validatePhoneValue(this.changes.phone, _t("Telefono"))) {
                return;
            }
        }

        // Validar campos obligatorios
        // Validar email solo cuando no se marco "No tiene mail"
        if (!this.uiState.no_tiene_mail) {
            if (!this.changes.email) {
                this._showValidationError(
                    _t("Correo electronico requerido"),
                    _t("Ingrese un correo electronico o marque 'No tiene mail'.")
                );
                return;
            }
            if (!this._validateEmailFormat(this.changes.email)) {
                this._showValidationError(
                    _t("Correo electronico invalido"),
                    _t("El formato del correo electronico no es valido.")
                );
                return;
            }
        }

        const missing = [];
        if (!this.changes.mobile) {
            missing.push(_t("Mobile"));
        }
        if (!this.changes.vat) {
            missing.push(_t("Document Number"));
        }
        if (!this.changes.l10n_latam_identification_type_id) {
            missing.push(_t("Document Type"));
        }
        // Fecha de nacimiento obligatoria para personas (no para empresa)
        if (!this.changes.is_company && !this.changes.birthdate_date) {
            missing.push(_t("Date of Birth"));
        }
        // Género obligatorio para personas cuando el módulo partner_gender está activo
        if (!this.changes.is_company && this.partnerGenderEnabled && !this.changes.gender) {
            missing.push(_t("Genero"));
        }

        // Fecha de nacimiento no puede ser futura
        if (!this.changes.is_company && this.changes.birthdate_date) {
            const today = new Date();
            today.setHours(0, 0, 0, 0);
            const birth = new Date(this.changes.birthdate_date);
            if (birth > today) {
                this._showValidationError(
                    _t("Invalid Date"),
                    _t("Date of birth cannot be in the future.")
                );
                return;
            }
        }

        if (missing.length) {
            return this.popup.add(ErrorPopup, {
                title: _t("Missing information"),
                body: _t("Please fill: %s", missing.join(", ")),
            });
        }

        // Ajustar company_type segun is_company
        this.changes.company_type = this.changes.is_company ? "company" : "person";

        // Si es empresa, sincronizar razon social y nombre
        if (this.changes.is_company) {
            if (this.changes.social_reason && !this.changes.name) {
                this.changes.name = this.changes.social_reason;
            } else if (this.changes.name && !this.changes.social_reason) {
                this.changes.social_reason = this.changes.name;
            }
        } else {
            // Si es persona, limpiar razon social
            this.changes.social_reason = false;
        }

        // Si no se ingreso ciudad, completar con el estado/departamento
        if (!this.changes.city && this.changes.state_id) {
            const state = this.pos.states?.find((item) => item.id === this.changes.state_id);
            if (state && state.name) {
                this.changes.city = state.name;
            }
        }

        // Aplicar defaults de configuracion si aun falta calle, ciudad, estado o pais
        if (!this.changes.street) {
            this.changes.street = this.pos.config.default_partner_street || false;
        }
        if (!this.changes.city) {
            this.changes.city = this.pos.config.default_partner_city || false;
        }
        if (!this.changes.country_id) {
            const c = this.pos.config.default_partner_country_id;
            this.changes.country_id = (Array.isArray(c) ? c[0] : c) || false;
        }
        if (!this.changes.state_id) {
            const s = this.pos.config.default_partner_state_id;
            this.changes.state_id = (Array.isArray(s) ? s[0] : s) || false;
        }

        // Si es empresa, ocultar fecha de nacimiento
        if (this.changes.is_company) {
            this.changes.birthdate_date = false;
        }

        // Delegar en el guardado estandar del POS para que cierre el popup y actualice
        // la lista de clientes. Nuestras validaciones ya se ejecutaron arriba.
        return super.saveChanges(...arguments);
    },
});
