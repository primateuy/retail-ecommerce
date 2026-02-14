/** @odoo-module */

import { _t } from "@web/core/l10n/translation";
import { ErrorPopup } from "@point_of_sale/app/errors/popups/error_popup";
import { PartnerDetailsEdit } from "@point_of_sale/app/screens/partner_list/partner_editor/partner_editor";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";

// Forzar uso del template personalizado del modulo
PartnerDetailsEdit.template = "pos_forum_customer_ui.PartnerDetailsEdit";

patch(PartnerDetailsEdit.prototype, {
    setup() {
        // Ejecutar la inicializacion base del editor
        super.setup(...arguments);

        // Servicios requeridos para validaciones y llamadas al backend
        this.orm = useService("orm");
        this.popup = useService("popup");

        // Inicializar campos adicionales usados por la UI personalizada
        const partner = this.props.partner;
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

        // Aplicar valores por defecto para calle y ciudad cuando corresponde
        this._applyDefaultAddressValues();
    },

    _applyDefaultAddressValues() {
        // Si ya hay datos, no sobreescribir
        if (!this.changes.street) {
            this.changes.street = this.pos.config.default_partner_street || false;
        }
        if (!this.changes.city) {
            this.changes.city = this.pos.config.default_partner_city || false;
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

    get identificationTypes() {
        // Obtener tipos de documento y filtrar por pais si aplica
        const allTypes = this.pos.identification_types || [];
        const countryId = this.changes.country_id;
        if (!countryId) {
            return allTypes;
        }
        return allTypes.filter(
            (item) => !item.country_id || item.country_id[0] === countryId
        );
    },

    get phonePlaceholder() {
        // Retornar un placeholder basado en el formato configurado en el pais
        const country = this.pos.countries?.find((c) => c.id === this.changes.country_id);
        if (country && country.pos_phone_format) {
            return country.pos_phone_format;
        }
        return _t("09x xxx xxx");
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
            return `${_t("Telefono")} - ${country.pos_phone_format}`;
        }
        return _t("Telefono");
    },

    onVatChange() {
        // Validar documento al modificar el campo
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

    _getCountryPhoneConfig() {
        // Obtener configuracion de telefono del pais seleccionado
        const country = this.pos.countries?.find((c) => c.id === this.changes.country_id);
        return {
            length: country?.pos_phone_length || 0,
            format: country?.pos_phone_format || "",
        };
    },

    _buildPhoneRegex(phoneFormat) {
        // Convertir formato simple a regex equivalente
        if (!phoneFormat) {
            return null;
        }
        const regexParts = [];
        for (const char of phoneFormat) {
            if (char === "x" || char === "X") {
                regexParts.push("\\d");
            } else if (/\d/.test(char)) {
                regexParts.push(char.replace(/[-/\\^$*+?.()|[\]{}]/g, "\\$&"));
            } else if (/\s/.test(char)) {
                regexParts.push("\\s?");
            } else {
                regexParts.push(char.replace(/[-/\\^$*+?.()|[\]{}]/g, "\\$&"));
            }
        }
        return new RegExp(`^${regexParts.join("")}$`);
    },

    _validatePhoneValue(value, label) {
        // Validar formato y longitud del telefono
        if (!value) {
            return;
        }
        const { length, format } = this._getCountryPhoneConfig();
        const digitsOnly = (value || "").replace(/\D/g, "");
        if (length && digitsOnly.length !== length) {
            this._showValidationError(
                _t("Invalid Phone"),
                _t("%s must be %s digits.", label, length)
            );
            return;
        }
        const regex = this._buildPhoneRegex(format);
        if (regex && !regex.test(value)) {
            this._showValidationError(
                _t("Invalid Phone"),
                _t("%s format does not match the required pattern.", label)
            );
        }
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

        // Ejecutar la consulta en backend segun el estado del registro
        let data = false;
        if (this.props.partner.id) {
            // Consultar con partner existente
            data = await this.orm.call("res.partner", "pos_consultar_rut", [
                this.props.partner.id,
            ]);
        } else {
            // Consultar sin guardar usando metodo de previsualizacion
            data = await this.orm.call("res.partner", "pos_consultar_rut_preview", [
                this.changes.vat,
            ]);
        }

        // Aplicar datos devueltos en el formulario
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
        this.changes.city = data.city || this.changes.city;
        this.changes.state_id = data.state_id && data.state_id[0];
        this.changes.country_id = data.country_id && data.country_id[0];
        this.changes.zip = data.zip || this.changes.zip;
        this.changes.phone = data.phone || this.changes.phone;
        this.changes.mobile = data.mobile || this.changes.mobile;
        this.changes.email = data.email || this.changes.email;
        this.changes.vat = data.vat || this.changes.vat;
        this.changes.is_company = Boolean(data.is_company);
        this.changes.company_type = data.company_type || this.changes.company_type;
    },

    saveChanges() {
        // Si partner_firstname no esta disponible, evitar enviar campos inexistentes
        if (!this.partnerFirstnameEnabled) {
            delete this.changes.firstname;
            delete this.changes.lastname;
        }

        // Si es empresa, limpiar nombres de persona
        if (this.partnerFirstnameEnabled && this.changes.is_company) {
            delete this.changes.firstname;
            delete this.changes.lastname;
        }

        // Validar campos obligatorios
        const missing = [];
        if (!this.changes.email) {
            missing.push(_t("Email"));
        }
        if (!this.changes.mobile) {
            missing.push(_t("Mobile"));
        }
        if (!this.changes.vat) {
            missing.push(_t("Document Number"));
        }
        if (!this.changes.l10n_latam_identification_type_id) {
            missing.push(_t("Document Type"));
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

        // Aplicar defaults de configuracion si aun falta calle o ciudad
        if (!this.changes.street) {
            this.changes.street = this.pos.config.default_partner_street || false;
        }
        if (!this.changes.city) {
            this.changes.city = this.pos.config.default_partner_city || false;
        }

        // Si es empresa, ocultar fecha de nacimiento
        if (this.changes.is_company) {
            this.changes.birthdate_date = false;
        }

        // Ejecutar guardado estándar
        return super.saveChanges(...arguments);
    },
});
