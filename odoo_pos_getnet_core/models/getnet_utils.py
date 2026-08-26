# -*- coding: utf-8 -*-
"""
Helpers puros para la integración Getnet/TransAct v4 por WebServices (SOAP).

Sin dependencia del ORM: cliente SOAP (requests + lxml), tablas de códigos
del manual y cálculos de montos. Todo lo que toca modelos vive en
payment_provider.py / payment_transaction.py.

Referencias:
- Manual de Integración TransAct v4.00.22 (TRA.GEN.MAN v1.3) — propiedades.
- Integración WebServices TransAct v4.0.09 (WS v02) — métodos y control.
"""

import logging
import threading

import requests
from lxml import etree

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Códigos de control de los WS (manual WS, "Propiedades de Control")
# ---------------------------------------------------------------------------
GETNET_RC_OK = 0
GETNET_RC_ERROR_FUNCIONAL = 1
GETNET_RC_ERROR_INTEGRACION = 2
GETNET_RC_ERROR_CONFIGURACION = 3
GETNET_RC_FACTURA_PENDIENTE = 9
# Sintético nuestro para fallas de transporte (HTTP no-2xx, XML inválido,
# SOAP Fault). No existe en el manual.
GETNET_RC_TRANSPORTE = 999

GETNET_RC_MSG = {
    GETNET_RC_OK: 'OK',
    GETNET_RC_ERROR_FUNCIONAL: 'Error funcional',
    GETNET_RC_ERROR_INTEGRACION: 'Error de integración',
    GETNET_RC_ERROR_CONFIGURACION: 'Error de configuración',
    GETNET_RC_FACTURA_PENDIENTE: 'Ya existe una factura pendiente en la terminal',
    GETNET_RC_TRANSPORTE: 'Error de comunicación con el concentrador TransAct',
}

# Resp_EstadoAvance (manual WS)
ESTADOAVANCE_SINDEFINIR = 0
ESTADOAVANCE_PENDIENTE_PROCESO = 1
ESTADOAVANCE_ENPROCESO = 2
ESTADOAVANCE_PROCESADA_SIN_CONFIRMAR = 3
ESTADOAVANCE_FINALIZADA_CORRECTAMENTE = 4
ESTADOAVANCE_FINALIZADA_ERROR = 5
ESTADOAVANCE_CANCELADA = 6

# El WSDL define Resp_EstadoAvance como un simpleType con enumeración de
# STRINGS (no un int): llega literalmente 'ESTADOAVANCE_ENPROCESO'. Los
# ordinales de arriba son nuestros y se mantienen porque son el valor
# persistido en payment.transaction.getnet_estado_avance.
GETNET_ESTADOAVANCE_NOMBRES = {
    'ESTADOAVANCE_SINDEFINIR': ESTADOAVANCE_SINDEFINIR,
    'ESTADOAVANCE_PENDIENTE_PROCESO': ESTADOAVANCE_PENDIENTE_PROCESO,
    'ESTADOAVANCE_ENPROCESO': ESTADOAVANCE_ENPROCESO,
    'ESTADOAVANCE_PROCESADA_SIN_CONFIRMAR': ESTADOAVANCE_PROCESADA_SIN_CONFIRMAR,
    'ESTADOAVANCE_FINALIZADA_CORRECTAMENTE': ESTADOAVANCE_FINALIZADA_CORRECTAMENTE,
    'ESTADOAVANCE_FINALIZADA_ERROR': ESTADOAVANCE_FINALIZADA_ERROR,
    'ESTADOAVANCE_CANCELADA': ESTADOAVANCE_CANCELADA,
}

ESTADOS_FINALES = (
    ESTADOAVANCE_FINALIZADA_CORRECTAMENTE,
    ESTADOAVANCE_FINALIZADA_ERROR,
    ESTADOAVANCE_CANCELADA,
)

# Operaciones de transacción (manual general, nivel TRANSACCION)
GETNET_OPERACION_VENTA = 'VTA'
GETNET_OPERACION_DEVOLUCION = 'DEV'

# FacturaNro cuando el cobro no tiene UNA factura origen (pago suelto,
# multi-factura, o cobro en el TPV antes de emitir el CFE).
#
# El WSDL declara FacturaNro con minOccurs="0", pero el concentrador lo
# exige a nivel funcional: omitirlo devuelve rc=2 'CAMPO REQUERIDO /
# VERIFIQUE / FACTURA' (probado contra el ambiente de integración el
# 17/8/2026; con 0 responde 'POSTEADA OK!'). Los demás Factura*
# (Monto/Gravado/IVA/ConsumidorFinal) sí son opcionales y se omiten.
GETNET_FACTURA_NRO_SIN_FACTURA = 0

# MonedaISO: TransAct SOLO acepta estos dos códigos (manual general).
# Cualquier otra moneda debe rechazarse con error claro, nunca asumir pesos.
GETNET_MONEDA_ISO = {
    'UYU': '0858',
    'USD': '0840',
}

# ---------------------------------------------------------------------------
# Contratos SOAP
# Validado contra los WSDL reales de testing (17/8/2026): el servicio es WCF
# con targetNamespace tempuri.org y SOAPAction 'tempuri.org/I<Svc>/<Metodo>'.
#
# Dos reglas del contrato que NO son opcionales:
#   1. Los hijos de un tipo complejo (Transaccion, Cierre, Configuracion...)
#      viven en el namespace de DataContract, no en tempuri: los XSD de esos
#      tipos declaran elementFormDefault="qualified" sobre su propio
#      targetNamespace. Solo el wrapper del método y sus parámetros simples
#      (TokenNro) son de tempuri.
#   2. DataContractSerializer espera los elementos en el ORDEN del xs:sequence
#      (alfabético). Un elemento fuera de orden no da error: se ignora en
#      silencio, y el campo queda nulo del lado del concentrador. Por eso los
#      payloads se emiten según GETNET_COMPLEX_TYPES y no en orden de dict.
# ---------------------------------------------------------------------------
GETNET_SOAP_NS = 'http://tempuri.org/'
GETNET_DATACONTRACT_NS = (
    'http://schemas.datacontract.org/2004/07/'
    'TransActV4ConcentradorWS.TransActV4Concentrador'
)
GETNET_ARRAYS_NS = 'http://schemas.microsoft.com/2003/10/Serialization/Arrays'
GETNET_TRANSACCION_SVC_PATH = 'Concentrador/TarjetasTransaccion_401.svc'
GETNET_TRANSACCION_CONTRACT = 'ITarjetasTransaccion_401'
GETNET_CIERRE_SVC_PATH = 'Concentrador/TarjetasCierre_400.svc'
GETNET_CIERRE_CONTRACT = 'ITarjetasCierre_400'

GETNET_URL_TESTING = 'https://testing-concentrador.getnet.com.uy'

GETNET_HTTP_TIMEOUT = 15  # por invocación; el manual sugiere <= 15 segundos

SOAP_ENV_NS = 'http://schemas.xmlsoap.org/soap/envelope/'

# ---------------------------------------------------------------------------
# Tipos complejos que EMITIMOS, en el orden exacto del xs:sequence del WSDL.
# 'children' mapea el nombre del elemento al tipo del hijo (el elemento
# 'Extendida' es de tipo TransaccionExtendida, etc.).
# ---------------------------------------------------------------------------
GETNET_COMPLEX_TYPES = {
    'Transaccion': {
        'fields': (
            'Comportamiento', 'Configuracion', 'EmisorId', 'EmpCod',
            'EmpHASH', 'Extendida', 'FacturaConsumidorFinal', 'FacturaMonto',
            'FacturaMontoGravado', 'FacturaMontoIVA', 'FacturaNro',
            'MonedaISO', 'Monto', 'MontoCashBack', 'MontoPropina', 'MultiEmp',
            'Operacion', 'TarjetaAlimentacion', 'TarjetaId', 'TarjetaTipo',
            'TermCod', 'TicketOriginal',
        ),
        'children': {
            'Comportamiento': 'ComportamientoTransaccion',
            'Configuracion': 'Configuracion',
            'Extendida': 'TransaccionExtendida',
        },
    },
    'ComportamientoTransaccion': {
        'fields': (
            'ModificarCuotas', 'ModificarDecretoLey', 'ModificarFactura',
            'ModificarMoneda', 'ModificarMontos', 'ModificarPlan',
            'ModificarTarjeta', 'ModificarTipoCuenta',
        ),
        'children': {},
    },
    'TransaccionExtendida': {
        'fields': (
            'Cuotas', 'DecretoLeyId', 'PlanId', 'PlanVentaId', 'TarjetaCVC',
            'TarjetaControl', 'TarjetaDocIdentidad', 'TarjetaNro',
            'TarjetaTitular', 'TarjetaVencimento', 'TipoCuentaId',
        ),
        'children': {},
    },
    # Configuracion es idéntica en ambos servicios (transacción y cierre).
    'Configuracion': {
        'fields': (
            'GUIModo', 'ImpresionCopias', 'ImpresionModo',
            'ImpresionNombreImpresora', 'ImpresionTipo',
            'ImpresionTipoImpresora', 'ModoEmulacion',
        ),
        'children': {},
    },
    'Cierre': {
        'fields': (
            'CierreCentralizado', 'Comportamiento', 'Configuracion', 'EmpCod',
            'EmpHASH', 'MultiEmp', 'ProcesadorId', 'TermCod',
        ),
        'children': {
            'Comportamiento': 'ComportamientoCierre',
            'Configuracion': 'Configuracion',
        },
    },
    'ComportamientoCierre': {
        'fields': ('ModificarProcesadorId',),
        'children': {},
    },
}

# Parámetros de método que son tipos complejos (el resto son escalares del
# namespace tempuri, como TokenNro).
GETNET_PARAM_TYPES = {
    'Transaccion': 'Transaccion',
    'Cierre': 'Cierre',
    # PostearConsultaUltimoCierre recibe un Cierre bajo otro nombre.
    'ConsultaUltimoCierre': 'Cierre',
}


# ---------------------------------------------------------------------------
# Transacciones de base de datos
# ---------------------------------------------------------------------------
def getnet_safe_commit(env):
    """
    Commit real, salvo durante tests: un commit dentro de una corrida de
    tests destruye los savepoints por-test de TransactionCase y aborta el
    resto de la suite. El guard es el flag ``testing`` del thread (patrón
    estándar de Odoo) más el test mode del registry (HttpCase).

    En producción los flujos de lock (claim/release) DEBEN commitear para
    hacerse visibles a otros workers antes de tocar el WS.
    """
    if (getattr(threading.current_thread(), 'testing', False)
            or env.registry.in_test_mode()):
        return
    env.cr.commit()


# ---------------------------------------------------------------------------
# Montos y moneda
# ---------------------------------------------------------------------------
def getnet_centavos(amount):
    """
    Convierte un importe a la representación TransAct: todos los montos se
    envían multiplicados por 100 (manual general, "Nomenclatura/Montos").
    """
    return int(round(amount * 100))


def getnet_entero_contrato(value, campo):
    """
    Normaliza un valor a xs:int del contrato.

    Hace falta porque TransAct devuelve varios identificadores como
    xs:double (Ticket, Lote, TransaccionId) y los persistimos como texto tal
    cual llegan; al reenviarlos en un campo declarado xs:int (TicketOriginal)
    un '1234.0' sería inválido y WCF descartaría el elemento.
    """
    if value in (None, '', False):
        return None
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        raise ValueError(
            "El valor de %s no es numérico y el contrato TransAct lo exige "
            "entero: %r" % (campo, value))


def getnet_lote_valido(value):
    """
    Devuelve el número de lote solo si es un lote de verdad.

    El concentrador manda ``Lote`` como xs:double y usa 0 (y '') para "sin
    lote asignado" — visto en respuestas no aprobadas del ambiente de
    testing. Como texto, '0' es truthy: sin esta normalización se crea un
    getnet.lote.cierre fantasma con lote '0'.
    """
    if value in (None, '', False):
        return ''
    texto = str(value).strip()
    try:
        if float(texto) == 0:
            return ''
    except (TypeError, ValueError):
        return texto
    return texto


def getnet_moneda_iso(currency_name):
    """
    Mapea el nombre de moneda Odoo (res.currency.name) al código MonedaISO
    de TransAct. Lanza ValueError para monedas no soportadas: la capa ORM
    debe convertirlo en UserError, nunca degradar a pesos por defecto.
    """
    code = GETNET_MONEDA_ISO.get(currency_name)
    if not code:
        raise ValueError(
            "TransAct solo opera en Pesos (UYU) o Dólares (USD); "
            "moneda no soportada: %s" % currency_name
        )
    return code


def getnet_montos_factura(lineas):
    """
    Calcula FacturaMonto / FacturaMontoGravado / FacturaMontoIVA en centavos
    a partir de las líneas de la factura, según el anexo "Ejemplos de Montos
    de Factura" del manual general:
      - FacturaMonto: total con impuestos.
      - FacturaMontoGravado: neto gravado (líneas con IVA > 0, sin importar
        la tasa). Alimenta la devolución de IVA (ley 19210) al cliente:
        el prorrateo multi-tasa no es cosmético.
      - FacturaMontoIVA: suma de IVA de todas las líneas.

    :param lineas: iterable de tuplas (neto, monto_iva) por línea.
    :return: dict con los tres montos en centavos.
    """
    total = 0.0
    gravado = 0.0
    iva = 0.0
    for neto, monto_iva in lineas:
        total += neto + monto_iva
        iva += monto_iva
        if monto_iva > 0:
            gravado += neto
    return {
        'FacturaMonto': getnet_centavos(total),
        'FacturaMontoGravado': getnet_centavos(gravado),
        'FacturaMontoIVA': getnet_centavos(iva),
    }


# ---------------------------------------------------------------------------
# Cliente SOAP
# ---------------------------------------------------------------------------
def getnet_build_soap_envelope(method, params, ns=GETNET_SOAP_NS):
    """
    Construye el envelope SOAP 1.1 para un método del concentrador.

    ``params`` es el dict de parámetros del método. Los escalares
    (p.ej. TokenNro) se emiten en el namespace del método; los tipos
    complejos declarados en GETNET_PARAM_TYPES (Transaccion, Cierre,
    ConsultaUltimoCierre) se emiten en el namespace de DataContract y con
    sus campos EN EL ORDEN DEL CONTRATO. Los valores None se omiten
    (semántica TransAct de "no setear" una propiedad, p.ej. DecretoLeyId).

    :return: bytes del envelope listo para postear.
    :raises ValueError: si un payload trae un campo que no existe en el
        contrato — WCF lo descartaría en silencio y el campo viajaría nulo.
    """
    envelope = etree.Element('{%s}Envelope' % SOAP_ENV_NS, nsmap={
        'soapenv': SOAP_ENV_NS,
        'tns': ns,
        'dc': GETNET_DATACONTRACT_NS,
    })
    etree.SubElement(envelope, '{%s}Header' % SOAP_ENV_NS)
    body = etree.SubElement(envelope, '{%s}Body' % SOAP_ENV_NS)
    method_el = etree.SubElement(body, '{%s}%s' % (ns, method))
    for key, value in params.items():
        if value is None:
            continue
        child = etree.SubElement(method_el, '{%s}%s' % (ns, key))
        type_name = GETNET_PARAM_TYPES.get(key)
        if type_name:
            _append_complex(child, value, type_name)
        elif isinstance(value, dict):
            raise ValueError(
                'Parámetro complejo desconocido para el contrato TransAct: '
                '%s (agregarlo a GETNET_PARAM_TYPES).' % key)
        else:
            child.text = _to_soap_text(value)
    return etree.tostring(
        envelope, xml_declaration=True, encoding='utf-8')


def _append_complex(parent, values, type_name):
    """
    Vuelca un tipo complejo respetando orden y namespace del contrato.

    El orden importa: DataContractSerializer recorre el xs:sequence y
    saltea lo que llega desordenado, dejando el campo nulo sin avisar.
    """
    spec = GETNET_COMPLEX_TYPES[type_name]
    desconocidos = set(values) - set(spec['fields'])
    if desconocidos:
        raise ValueError(
            'Campos ajenos al tipo TransAct %s: %s' % (
                type_name, ', '.join(sorted(desconocidos))))
    for name in spec['fields']:
        value = values.get(name)
        if value is None:
            continue
        child = etree.SubElement(parent, '{%s}%s' % (GETNET_DATACONTRACT_NS, name))
        child_type = spec['children'].get(name)
        if child_type:
            _append_complex(child, value, child_type)
        else:
            child.text = _to_soap_text(value)


def _to_soap_text(value):
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return str(value)


def _soap_fault_data(root):
    """Respuesta sintética de transporte si el sobre trae un SOAP Fault."""
    fault = root.find('.//{%s}Fault' % SOAP_ENV_NS)
    if fault is None:
        return None
    faultstring = fault.findtext('faultstring') or fault.findtext(
        '{%s}Reason/{%s}Text' % (SOAP_ENV_NS, SOAP_ENV_NS)) or 'SOAP Fault'
    return {
        'Resp_CodigoRespuesta': GETNET_RC_TRANSPORTE,
        'Resp_MensajeError': faultstring,
    }


def _element_to_tree(element):
    """
    Convierte un elemento en dict/list/str preservando la jerarquía.

    - Hoja -> texto.
    - ArrayOfstring (namespace de Arrays de WCF) -> lista de textos: así el
      Voucher queda bajo su propia clave y no bajo 'string'.
    - Hijos con nombre repetido -> lista (arrays de tipos complejos).
    """
    hijos = [h for h in element if isinstance(h.tag, str)]
    if not hijos:
        return (element.text or '').strip()
    if all(etree.QName(h).namespace == GETNET_ARRAYS_NS
           and etree.QName(h).localname == 'string' for h in hijos):
        return [(h.text or '').strip() for h in hijos]
    data = {}
    for hijo in hijos:
        tag = etree.QName(hijo).localname
        valor = _element_to_tree(hijo)
        if tag in data:
            if not isinstance(data[tag], list):
                data[tag] = [data[tag]]
            data[tag].append(valor)
        else:
            data[tag] = valor
    return data


def getnet_parse_soap_tree(xml_bytes):
    """
    Parsea la respuesta SOAP preservando la jerarquía del contrato.

    Necesario para RespuestaConsultarCierre: DatosCierre es un array de
    IDatosCierre y cada uno cuelga un árbol Extendida > Productos > Monedas
    > Planes > (Nacionales|Extranjeras) > (Venta|Devolucion|Anulacion) donde
    los nombres de totales (MontoVenta, CantVenta, ...) se repiten en varios
    niveles. Aplanar eso mezcla los totales del cierre con los subtotales
    por plan.

    :return: dict del contenido del Body (o respuesta sintética de
             transporte ante Fault / XML inválido).
    """
    try:
        root = etree.fromstring(xml_bytes)
    except (etree.XMLSyntaxError, ValueError) as exc:
        return {
            'Resp_CodigoRespuesta': GETNET_RC_TRANSPORTE,
            'Resp_MensajeError': 'Respuesta no parseable del concentrador: %s' % exc,
        }
    fault = _soap_fault_data(root)
    if fault is not None:
        return fault
    body = root.find('{%s}Body' % SOAP_ENV_NS)
    if body is None:
        return {}
    tree = _element_to_tree(body)
    return tree if isinstance(tree, dict) else {}


def getnet_array_items(value):
    """
    Normaliza un array WCF (ArrayOfX) a una lista de items.

    El wrapper tiene un único tipo de hijo repetido; con un solo elemento
    el parser devuelve un dict, con varios una lista. Esta función tapa esa
    diferencia (y tolera que el array venga vacío o ausente).
    """
    if value in (None, ''):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        if len(value) == 1:
            interno = next(iter(value.values()))
            return interno if isinstance(interno, list) else [interno]
        return [value]
    return [value]


def _flatten_tree(tree, data):
    """Aplana un árbol a {nombre_local: valor} (ver getnet_parse_soap_response)."""
    for key, value in tree.items():
        if isinstance(value, dict):
            _flatten_tree(value, data)
            continue
        if isinstance(value, list) and any(
                isinstance(v, dict) for v in value):
            for item in value:
                if isinstance(item, dict):
                    _flatten_tree(item, data)
            continue
        if key in data:
            if not isinstance(data[key], list):
                data[key] = [data[key]]
            if isinstance(value, list):
                data[key].extend(value)
            else:
                data[key].append(value)
        else:
            data[key] = value


def getnet_parse_soap_response(xml_bytes):
    """
    Parsea la respuesta SOAP y la aplana a un dict {nombre_local: valor}.

    Es la vista cómoda para el servicio de transacciones, donde los campos
    que persistimos no colisionan entre niveles (verificado contra el WSDL:
    TokenNro/Ticket/Lote/NroAutorizacion/Aprobada/TarjetaId/TarjetaTipo son
    únicos y solo aparecen en la raíz de RespuestaConsultarTransaccion).
    El Voucher (ArrayOfstring) queda como lista bajo la clave 'Voucher'.

    Para el servicio de CIERRE hay que usar getnet_parse_soap_tree: ahí los
    nombres sí se repiten entre niveles.
    """
    tree = getnet_parse_soap_tree(xml_bytes)
    data = {}
    _flatten_tree(tree, data)
    return data


def getnet_soap_call(base_url, svc_path, contract, method, params,
                     timeout=GETNET_HTTP_TIMEOUT, ns=GETNET_SOAP_NS):
    """
    Invoca un método SOAP del concentrador TransAct.

    :return: tupla (data, request_xml, response_xml) donde ``data`` es el
             dict aplanado de la respuesta. Los errores de transporte nunca
             levantan excepción: se devuelven como respuesta sintética con
             Resp_CodigoRespuesta = GETNET_RC_TRANSPORTE, para que el motor
             de polling decida (el manual obliga a consultar hasta obtener
             respuesta).
    """
    endpoint = '%s/%s' % (base_url.rstrip('/'), svc_path)
    request_xml = getnet_build_soap_envelope(method, params, ns=ns)
    headers = {
        'Content-Type': 'text/xml; charset=utf-8',
        # Confirmado contra el WSDL: soapAction="http://tempuri.org/
        # ITarjetasTransaccion_401/PostearTransaccion" (ídem cierre).
        'SOAPAction': '"%s%s/%s"' % (ns, contract, method),
    }
    request_str = request_xml.decode('utf-8', errors='replace')
    try:
        response = requests.post(
            endpoint, data=request_xml, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        _logger.warning('Getnet SOAP %s: error de transporte: %s', method, exc)
        data = {
            'Resp_CodigoRespuesta': GETNET_RC_TRANSPORTE,
            'Resp_MensajeError': 'Error de comunicación: %s' % exc,
        }
        return data, request_str, ''
    response_str = response.text or ''
    if not response.ok:
        _logger.warning(
            'Getnet SOAP %s: HTTP %s: %s',
            method, response.status_code, response_str[:500])
        data = {
            'Resp_CodigoRespuesta': GETNET_RC_TRANSPORTE,
            'Resp_MensajeError': 'HTTP %s del concentrador' % response.status_code,
        }
        return data, request_str, response_str
    data = getnet_parse_soap_response(response.content)
    return data, request_str, response_str


# ---------------------------------------------------------------------------
# Lectura tolerante de la respuesta
# ---------------------------------------------------------------------------
def getnet_rc(data):
    """Resp_CodigoRespuesta como int (transporte si no es parseable)."""
    try:
        return int(data.get('Resp_CodigoRespuesta') or 0)
    except (TypeError, ValueError):
        return GETNET_RC_TRANSPORTE


def getnet_estado_avance(data):
    """
    Resp_EstadoAvance normalizado a nuestro ordinal.

    El WSDL lo declara como enumeración de strings
    ('ESTADOAVANCE_ENPROCESO', ...); se acepta también el entero por si
    alguna respuesta lo serializa así. SINDEFINIR si falta o no se reconoce.
    """
    value = data.get('Resp_EstadoAvance')
    if value is None:
        return ESTADOAVANCE_SINDEFINIR
    texto = str(value).strip()
    if texto in GETNET_ESTADOAVANCE_NOMBRES:
        return GETNET_ESTADOAVANCE_NOMBRES[texto]
    try:
        return int(texto)
    except (TypeError, ValueError):
        return ESTADOAVANCE_SINDEFINIR


def getnet_finalizado(data):
    """
    Flag de finalización de la consulta.

    Nombres reales del contrato (WSDL): Resp_TransaccionFinalizada en el
    servicio de transacciones y Resp_CierreFinalizado en el de cierres. El
    'Resp_Finalizado' de la tabla del manual no existe en ningún contrato.
    """
    for key in ('Resp_TransaccionFinalizada', 'Resp_CierreFinalizado'):
        value = data.get(key)
        if value is not None:
            return str(value).strip().lower() == 'true'
    return False


def getnet_bool(data, key):
    """Booleano SOAP tolerante ('true'/'false'/None)."""
    value = data.get(key)
    if value is None:
        return False
    return str(value).strip().lower() == 'true'


def getnet_segundos_reconsulta(data, default):
    """
    Segundos hasta la próxima consulta: TokenSegundosConsultar en el posteo,
    Resp_TokenSegundosReConsultar en las consultas. El server manda el ritmo.
    """
    for key in ('Resp_TokenSegundosReConsultar', 'TokenSegundosConsultar'):
        try:
            value = int(data.get(key))
            if value > 0:
                return value
        except (TypeError, ValueError):
            continue
    return default
