# -*- coding: utf-8 -*-
"""
LECTURA PREVIA DE LA TARJETA — TODO LO QUE EL MANUAL NO CONFIRMA, EN UN SOLO
LUGAR.

El manual de TransAct v4 (WS v02, pág. 9; General v1.3, «Tabla de Propiedades
de Datos de Tarjeta») documenta los métodos PostearConsultaDatosTarjeta /
ConsultarDatosTarjeta del servicio de Transacciones, pero remite al WSDL para
los tipos complejos, y el WSDL no lo tenemos (el concentrador de testing está
caído desde el 26/09/2026). Cada nombre marcado SUPUESTO sale del manual o de
la analogía con los métodos que sí están confirmados contra el WSDL real
(PostearTransaccion / ConsultarTransaccion). Cuando llegue el WSDL, se ajusta
ACÁ y en ningún otro lado.

Si algo de esto no coincide con el concentrador real, la lectura falla, y la
venta pasa sola a selección manual (modo A) con un aviso al cajero: el cobro
nunca queda trabado por esto.
"""

from odoo.addons.odoo_pos_getnet_core.models import getnet_utils

# Métodos (manual WS v02, pág. 9): CONFIRMADO por el manual.
METODO_POSTEAR = 'PostearConsultaDatosTarjeta'
METODO_CONSULTAR = 'ConsultarDatosTarjeta'

# SUPUESTO: el parámetro del posteo se llama como su tipo, «ConsultaTarjeta»
# (el manual dice «objeto de tipo ConsultaTarjeta»; en PostearTransaccion el
# parámetro «Transaccion» es de tipo Transaccion).
PARAMETRO_POSTEAR = 'ConsultaTarjeta'
TIPO_CONSULTA = 'ConsultaTarjeta'

# SUPUESTO: ConsultarDatosTarjeta recibe el token como ConsultarTransaccion y
# CancelarTransaccion (parámetro simple «TokenNro»), y PostearConsultaDatos-
# Tarjeta lo devuelve como «TokenNro», igual que PostearTransaccion.
PARAMETRO_CONSULTAR_TOKEN = 'TokenNro'

# SUPUESTO: campos de ConsultaTarjeta. El manual lista como datos mínimos
# EmpCod, TermCod y MultiEmp; EmpHASH va en todo pedido autenticado; y
# MontoTAP figura en el control de cambios v1.1 («MontoTAP en lectura previa de
# tarjeta antes de la transacción»). Orden alfabético, como exige
# DataContractSerializer para el xs:sequence.
CAMPOS_CONSULTA = ('EmpCod', 'EmpHASH', 'MontoTAP', 'MultiEmp', 'TermCod')

# SUPUESTO: la bandera de «terminó» en ConsultarDatosTarjeta. En las
# transacciones es Resp_TransaccionFinalizada y en los cierres
# Resp_CierreFinalizado; el manual nombra un genérico Resp_Finalizado. Se
# acepta cualquiera de estos.
BANDERAS_FINALIZADO = (
    'Resp_DatosTarjetaFinalizada', 'Resp_ConsultaFinalizada',
    'Resp_Finalizado', 'Resp_TransaccionFinalizada',
)

# CONFIRMADO por el manual (General v1.3): propiedades de DatosTarjeta.
CAMPOS_DATOS_TARJETA = (
    'TarjetaId', 'TarjetaTipo', 'TarjetaNro', 'TarjetaIIN', 'EmisorId',
    'TarjetaLargo', 'TarjetaUlt4', 'TarjetaPrestaciones',
)

# Nunca a un log: el número completo o el titular. El BIN (TarjetaIIN) sí,
# que es lo que hace falta para diagnosticar el primer cobro real.
CAMPOS_SENSIBLES = ('TarjetaNro', 'TarjetaTitular', 'TarjetaVencimiento',
                    'TarjetaDocIdentidad', 'TarjetaCVC', 'EmpHASH')

# Se registra el tipo en el builder SOAP del núcleo (que falla fuerte ante un
# campo ajeno al contrato: por eso tiene que estar declarado).
getnet_utils.GETNET_COMPLEX_TYPES.setdefault(TIPO_CONSULTA, {
    'fields': CAMPOS_CONSULTA,
    'children': {},
})
getnet_utils.GETNET_PARAM_TYPES.setdefault(PARAMETRO_POSTEAR, TIPO_CONSULTA)

# Cuánto espera la PANTALLA a que la clienta pase la tarjeta (sondeo corto
# desde el cliente). Pasado esto, la venta pasa a selección manual.
LECTURA_TOPE_SEGUNDOS = 60
# Cada consulta de lectura desde el server: corta.
LECTURA_CONSULTA_SEGUNDOS = 4
# El pinpad guarda los datos leídos 30 s (manual WS, pág. 9): la transacción
# tiene que postearse antes. Con margen.
LECTURA_VIGENCIA_SEGUNDOS = 25
