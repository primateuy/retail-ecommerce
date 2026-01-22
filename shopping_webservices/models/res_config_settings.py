from odoo import fields, api, models;

import logging;

_logger = logging.getLogger(__name__);



class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    rut = fields.Char(string="RUT", config_parameter='shopping_webservices.rut');
    # tecnologia = fields.Selection([
    #     ('lecueder', 'Lecueder'),
    #     ('costa_urbana', 'Costa Urbana'),
    # ], string="Tecnología", config_parameter='shopping_webservices.tecnologia', default='lecueder');
    password = fields.Char(string="Password", config_parameter='shopping_webservices.password');
    nombreContrato = fields.Char(string="Nombre Contrato", config_parameter='shopping_webservices.nombre_contrato');
    nroContrato = fields.Char(string="Nro Contrato", config_parameter='shopping_webservices.nro_contrato');
    codigoRubro = fields.Char(string="Código Rubro", config_parameter='shopping_webservices.codigo_rubro');
    codigoShopping = fields.Char(string="Código Shopping", config_parameter='shopping_webservices.codigo_shopping');
    urlContratoRUT = fields.Char(string="URL Contrato RUT", config_parameter='shopping_webservices.url_contrato_rut');
    urlDatosContrato = fields.Char(string="URL Datos Contrato", config_parameter='shopping_webservices.url_datos_contrato');
    urlDeclaracionVentas = fields.Char(string="URL Declaración Ventas", config_parameter='shopping_webservices.url_declaracion_ventas');
    urlAnulacionCFE = fields.Char(string="URL Anulación CFE", config_parameter='shopping_webservices.url_anulacion_cfe');
    urlAnulacionCFEPorContratoYFecha = fields.Char(string="URL Anulación CFE por Contrato y Fecha", config_parameter='shopping_webservices.url_anulacion_cfe_por_contrato_y_fecha');
    