# -*- coding: utf-8 -*-
"""
procesador_cfdi.py
------------------
Motor de procesamiento y auditoria de descargas masivas de CFDI 4.0 (SAT Mexico).

Responsabilidades:
  1. Leer Excel "crudos" (SAT o portales contables) con basura en las primeras filas.
  2. Mapear columnas con tolerancia a nombres (alias sin acentos/mayusculas/espacios).
  3. Leer el FORMATO de las celdas (openpyxl) para detectar Notas de Credito marcadas
     solo con color (los "ojos de contador").
  4. Aplicar en cascada las 6 reglas fiscales.
  5. Calcular el Total Deducible del Mes y exportar el Excel depurado de 3 hojas.

Autor: Sistema Contable - modulo de procesamiento
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

import lector_xml
import perfiles
import estatus_sat
import reglas_md
from tipo_cambio import obtener_tasa as tc_obtener_tasa

try:
    from openpyxl import load_workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    OPENPYXL_OK = True
except ImportError:  # pragma: no cover
    OPENPYXL_OK = False


# =============================================================================
# 0. CONFIGURACIONX
# =============================================================================

RUTA_CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config_reglas.json")

CONFIG_POR_DEFECTO: Dict[str, Any] = {
    "tope_efectivo": 2000.00,
    "aplicar_tope_efectivo_a_egresos": False,
    "aplicar_lista_negra_a_nomina_y_pagos": False,
    "filas_a_escanear_encabezado": 30,
    "lista_negra": [
        "gym", "gimnasio", "cine", "cinepolis", "cinemex", "despensa", "supermercado",
        "restaurante", "restaurant", "bar", "cantina", "cerveza", "vino", "licor",
        "tabaco", "cigarro", "boliche", "casino", "apuesta", "netflix", "spotify",
        "videojuego", "juguete", "ropa", "zapatos", "perfume", "joyeria", "mascota",
        "veterinaria", "crucero", "viaje de placer", "boletos de avion",
        "colegiatura", "funeral", "florera", "floreria", "regalo", "propina"
    ],
    "lista_negra_frases": [
        "consumo en restaurante", "alimentos y bebidas", "servicio de comedor"
    ],
    "rfc_exentos_lista_negra": [],
    "colores_nota_credito": ["FFFF0000", "FFC00000", "FF9C0006", "FFCC0000"],
    "detectar_rojo_por_heuristica": True,
    "detectar_relleno_rojo": True,
    "columnas_clave_para_color": ["Total", "UUID", "Tipo Comprobante", "Descripcion"],
    "tratar_total_negativo_como_egreso": True
}


def cargar_config(ruta: str = RUTA_CONFIG) -> Dict[str, Any]:
    """Carga config_reglas.json y completa lo que falte con los valores por defecto."""
    cfg = dict(CONFIG_POR_DEFECTO)
    if os.path.exists(ruta):
        try:
            with open(ruta, "r", encoding="utf-8") as fh:
                usuario = json.load(fh)
            if isinstance(usuario, dict):
                cfg.update({k: v for k, v in usuario.items() if v is not None})
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[AVISO] No se pudo leer {ruta}: {exc}. Se usan valores por defecto.")
    return cfg


# =============================================================================
# 1. NORMALIZACION DE TEXTO Y CLAVES
# =============================================================================

def normalizar(texto: Any) -> str:
    """minusculas, sin acentos, sin signos, espacios colapsados. '' si es nulo."""
    if texto is None or (isinstance(texto, float) and pd.isna(texto)):
        return ""
    s = str(texto).strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _separar_camel(texto: str) -> str:
    """
    'FormaDePago' -> 'Forma De Pago', 'UsoCFDI' -> 'Uso CFDI', 'EstadoSAT' -> 'Estado SAT'.
    Muchos portales escriben los encabezados pegados; sin esto no coinciden con
    ningun alias y la columna se pierde en silencio.
    """
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(texto))
    return re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", s)


def normalizar_encabezado(texto: Any) -> str:
    """Como normalizar(), pero separando primero las mayusculas pegadas."""
    if texto is None:
        return ""
    return normalizar(_separar_camel(str(texto)))


def limpiar_clave(valor: Any, longitud: Optional[int] = None) -> str:
    """
    Extrae la clave oficial de un valor del SAT.
      '01 - Efectivo'      -> '01'
      'I - Ingreso'        -> 'I'
      'PUE (Una exhibicion)' -> 'PUE'
      1                    -> '01'   (con longitud=2)
    """
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        if float(valor).is_integer():
            s = str(int(valor))
        else:
            s = str(valor)
    else:
        s = str(valor)
    s = s.strip()
    if not s or s.lower() in ("nan", "none", "nat"):
        return ""
    # Corta en el primer separador tipico: '-', '–', '|', ':', '(' , '/'
    s = re.split(r"[-–—|:/(]", s)[0]
    s = re.sub(r"[^A-Za-z0-9]", "", s).upper()
    if longitud and s.isdigit():
        s = s.zfill(longitud)
    return s


def a_numero(valor: Any) -> float:
    """Convierte '$ 1,234.56', '1.234,56', ' (500) ' o texto sucio a float."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return 0.0
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        return float(valor)
    s = str(valor).strip()
    if not s:
        return 0.0
    negativo = s.startswith("(") and s.endswith(")")
    s = re.sub(r"[^0-9,.\-]", "", s)
    if not s:
        return 0.0
    # Formato europeo: 1.234,56 -> 1234.56
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".") if re.search(r",\d{1,2}$", s) else s.replace(",", "")
    try:
        num = float(s)
    except ValueError:
        return 0.0
    return -abs(num) if negativo else num


# =============================================================================
# 2. TOLERANCIA A NOMBRES DE COLUMNAS (DICCIONARIO DE ALIAS)
# =============================================================================

ALIAS_COLUMNAS: Dict[str, List[str]] = {
    "UUID": ["uuid", "folio fiscal", "foliofiscal", "folio uuid", "uuid fiscal",
             "folio fiscal uuid", "id cfdi"],
    "RFC Emisor": ["rfc emisor", "emisor rfc", "rfc del emisor", "rfc emisor receptor",
                   "rfc que emite"],
    "Nombre Emisor": ["nombre emisor", "razon social emisor", "emisor",
                      "nombre o razon social del emisor", "proveedor"],
    "RFC Receptor": ["rfc receptor", "receptor rfc", "rfc del receptor", "rfc cliente"],
    "Nombre Receptor": ["nombre receptor", "razon social receptor", "receptor",
                        "nombre o razon social del receptor", "cliente"],
    "Fecha Emision": ["fecha emision", "fecha de emision", "fecha", "fecha factura",
                      "fecha timbrado", "fecha de timbrado", "fecha del comprobante"],
    "Tipo Comprobante": ["tipo comprobante", "tipo de comprobante", "efecto comprobante",
                         "efecto del comprobante", "tipo cfdi", "tipo de cfdi", "tipo"],
    "Forma Pago": ["forma pago", "forma de pago", "formapago", "clave forma pago"],
    "Metodo Pago": ["metodo pago", "metodo de pago", "metodopago", "clave metodo pago"],
    "Uso CFDI": ["uso cfdi", "uso del cfdi", "clave uso cfdi"],
    "Subtotal": ["subtotal", "sub total", "importe"],
    "Descuento": ["descuento", "descuentos"],
    # Las retenciones van ANTES que el IVA: asi 'IVA Retenido' no cae en 'IVA'.
    "IVA Retenido": ["iva retenido", "retencion iva", "retencion de iva", "ret iva",
                     "iva ret", "total iva retenido", "impuesto retenido iva",
                     "retenido iva", "iva retenciones"],
    "ISR Retenido": ["isr retenido", "retencion isr", "retencion de isr", "ret isr",
                     "isr ret", "total isr retenido", "impuesto retenido isr",
                     "retenido isr", "isr", "isr xml", "isr del xml"],
    "Retenciones": ["retenciones", "total impuestos retenidos", "impuestos retenidos",
                    "total retenciones", "total de retenciones", "total retenido",
                    "impuesto retenido", "impuestos retenidos totales"],
    "IEPS Retenido": ["ieps retenido", "retencion ieps", "retencion de ieps",
                      "ret ieps", "total ieps retenido"],
    "IEPS": ["ieps", "ieps trasladado", "total ieps", "ieps trasladados",
             "impuesto especial", "total impuesto especial"],
    "Total Trasladados": ["total trasladados", "total de trasladados",
                          "suma de trasladados"],
    # Bases por tasa: es lo que pide la declaracion de IVA
    "Base 16": ["iva 16 base", "base 16", "base iva 16", "base tasa 16",
                "compras y gastos tasa 16", "base gravada 16", "valor actos 16",
                "actos gravados 16"],
    "Base 8": ["iva 8 base", "base 8", "base iva 8", "base tasa 8",
               "compras y gastos tasa 8", "base gravada 8", "valor actos 8"],
    "Base 0": ["iva cero base", "base 0", "base cero", "base tasa 0",
               "base gravada 0", "valor actos 0", "actos tasa 0",
               "compras y gastos tasa 0"],
    "Base Exento": ["iva exento base", "base exento", "base exenta",
                    "actos exentos", "valor actos exentos", "base exentos",
                    "compras y gastos exentos"],
    "IVA Tasa 8": ["iva 8 importe", "iva 8", "importe iva 8"],
    "Tipo Cambio CFDI": ["tipo cambio", "tipo de cambio", "tipo cambio p",
                         "tipo de cambio del cfdi"],
    "IVA": ["iva", "total impuestos trasladados", "impuesto trasladado", "traslados",
            "iva trasladado", "impuestos trasladados", "total iva", "iva 16",
            "iva 16 00", "total traslados", "total de traslados", "iva causado",
            "traslado iva", "total impuesto trasladado", "iva trasladados",
            "importe iva", "monto iva"],
    "Percepciones": ["total percepciones", "percepciones", "total de percepciones",
                     "total percepcion", "sueldos y salarios", "total gravado"],
    "Deducciones": ["total deducciones", "deducciones", "total de deducciones",
                    "total deduccion", "descuentos de nomina"],
    "Otros Pagos": ["otros pagos", "total otros pagos", "otrospagos",
                    "total de otros pagos"],
    "Total": ["total", "monto total", "importe total", "total factura",
              "total del comprobante", "gran total"],
    "Descripcion": ["descripcion", "concepto", "conceptos", "descripcion concepto",
                    "descripcion del concepto", "descripcion del servicio", "detalle"],
    "Monto Pagado": ["monto pagado", "importe pagado", "total pagado", "monto del pago",
                     "importe del pago", "pagado", "monto"],
    "Moneda": ["moneda", "tipo moneda"],
    "Estatus": ["estatus", "estado", "estatus cfdi", "estado del comprobante",
                "estatus del comprobante", "vigente cancelado", "estado sat"],
    "Serie": ["serie"],
    "Folio": ["folio", "folio interno"],
}

# Palabras que delatan la fila de encabezados reales
PALABRAS_ENCABEZADO = {"uuid", "folio fiscal", "rfc", "rfc emisor", "rfc receptor",
                       "total", "fecha", "tipo comprobante", "efecto comprobante",
                       "forma pago", "metodo pago", "subtotal", "descripcion", "concepto"}


def _puntuar_fila_encabezado(valores: List[Any]) -> int:
    """Cuantas celdas de la fila parecen encabezados de CFDI."""
    puntos = 0
    for v in valores:
        n = normalizar_encabezado(v)
        if not n or len(n) > 60:
            continue
        if n in PALABRAS_ENCABEZADO:
            puntos += 2
            continue
        for alias in ALIAS_COLUMNAS.values():
            if n in alias:
                puntos += 2
                break
        else:
            if any(p in n for p in ("rfc", "uuid", "folio fiscal", "comprobante",
                                    "forma de pago", "metodo de pago")):
                puntos += 1
    return puntos


def mapear_columnas(encabezados: List[Any]) -> Dict[int, str]:
    """
    Devuelve {indice_columna: nombre_canonico}.
    Pasada 1: coincidencia exacta del alias. Pasada 2: coincidencia por contencion
    (alias mas largo primero) para no confundir 'Total' con 'Total Impuestos'.
    """
    mapa: Dict[int, str] = {}
    usados: set = set()
    normalizados = [normalizar_encabezado(h) for h in encabezados]

    # --- Pasada 1: el encabezado ES un alias, tal cual ---------------------
    for idx, n in enumerate(normalizados):
        if not n:
            continue
        for canon, alias in ALIAS_COLUMNAS.items():
            if canon in usados:
                continue
            if n in alias:
                mapa[idx] = canon
                usados.add(canon)
                break

    # --- Pasada 2: el alias aparece dentro del encabezado ------------------
    pendientes = [(canon, sorted(alias, key=len, reverse=True))
                  for canon, alias in ALIAS_COLUMNAS.items() if canon not in usados]
    for idx, n in enumerate(normalizados):
        if idx in mapa or not n:
            continue
        for canon, alias in pendientes:
            if canon in usados:
                continue
            if any(_alias_encaja(a, n, canon) for a in alias
                   if len(a) >= 4 and a not in ALIAS_SOLO_EXACTOS):
                mapa[idx] = canon
                usados.add(canon)
                break
    return mapa


# Alias demasiado genericos: valen para una coincidencia exacta, pero no para
# buscarlos dentro de otro encabezado. Sin esto 'NumDiasPagados' cae en
# 'Monto Pagado' y 'TipoCambioP' cae en 'Tipo Comprobante'.
ALIAS_SOLO_EXACTOS = {"importe", "monto", "total", "tipo", "pagado", "concepto",
                      "detalle", "emisor", "receptor", "cliente", "proveedor"}

# Palabras que cambian el significado de una columna de dinero. Si sobran despues
# de quitar el alias, la coincidencia NO vale: 'IVA 16 Base' no es el IVA, y
# 'IEPS Retenido' no es el IEPS trasladado.
MODIFICAN_IMPORTE = {"base", "retenido", "retenidos", "retencion", "retenciones",
                     "exento", "exentos", "cero", "acreditable", "pendiente",
                     "anterior", "insoluto", "saldo", "dias", "numero", "num",
                     "cantidad", "porcentaje", "tasa", "cuota", "clave", "tipo"}

CANONES_IMPORTE = {"Subtotal", "Descuento", "IVA", "IVA Tasa 8", "IEPS",
                   "IVA Retenido", "ISR Retenido", "IEPS Retenido", "Retenciones",
                   "Total", "Monto Pagado", "Percepciones", "Deducciones",
                   "Otros Pagos", "Total Trasladados"}


def _alias_encaja(alias: str, encabezado: str, canon: str) -> bool:
    """
    Acepta el alias solo si aparece como palabra(s) completa(s) y lo que sobra
    del encabezado no le cambia el sentido.
    """
    if not re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", encabezado):
        return False
    sobra = re.sub(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", " ", encabezado)
    restantes = [p for p in sobra.split() if p]
    if not restantes:
        return True
    if len(restantes) > 2:
        return False
    if canon in CANONES_IMPORTE and any(p in MODIFICAN_IMPORTE for p in restantes):
        return False
    return True


# =============================================================================
# 2b. CATALOGOS OFICIALES DEL SAT (para mostrar claves legibles)
# =============================================================================

TIPOS_COMPROBANTE: Dict[str, str] = {
    "I": "Ingreso", "E": "Egreso", "N": "Nomina", "P": "Pago", "T": "Traslado",
}

FORMAS_PAGO: Dict[str, str] = {
    "01": "Efectivo", "02": "Cheque nominativo", "03": "Transferencia electronica",
    "04": "Tarjeta de credito", "05": "Monedero electronico", "06": "Dinero electronico",
    "08": "Vales de despensa", "12": "Dacion en pago", "13": "Pago por subrogacion",
    "14": "Pago por consignacion", "15": "Condonacion", "17": "Compensacion",
    "23": "Novacion", "24": "Confusion", "25": "Remision de deuda",
    "26": "Prescripcion o caducidad", "27": "A satisfaccion del acreedor",
    "28": "Tarjeta de debito", "29": "Tarjeta de servicios",
    "30": "Aplicacion de anticipos", "31": "Intermediario pagos", "99": "Por definir",
}

METODOS_PAGO: Dict[str, str] = {
    "PUE": "Pago en una sola exhibicion",
    "PPD": "Pago en parcialidades o diferido",
}

USOS_CFDI: Dict[str, str] = {
    "G01": "Adquisicion de mercancias",
    "G02": "Devoluciones, descuentos o bonificaciones",
    "G03": "Gastos en general",
    "I01": "Construcciones", "I02": "Mobiliario y equipo de oficina",
    "I03": "Equipo de transporte", "I04": "Equipo de computo",
    "I05": "Dados, troqueles, moldes y herramental", "I06": "Comunicaciones telefonicas",
    "I07": "Comunicaciones satelitales", "I08": "Otra maquinaria y equipo",
    "D01": "Honorarios medicos y hospitalarios",
    "D02": "Gastos medicos por incapacidad", "D03": "Gastos funerales",
    "D04": "Donativos", "D05": "Intereses de creditos hipotecarios",
    "D06": "Aportaciones voluntarias al SAR",
    "D07": "Primas de seguros de gastos medicos",
    "D08": "Transportacion escolar obligatoria",
    "D09": "Depositos en cuentas para el ahorro",
    "D10": "Pagos por servicios educativos",
    "S01": "Sin efectos fiscales", "CP01": "Pagos", "CN01": "Nomina",
    "P01": "Por definir",
}

# Codigos ISO que el SAT usa con mas frecuencia
MONEDAS_ISO = {"MXN", "USD", "EUR", "CAD", "GBP", "JPY", "CHF", "XXX"}

# Muchos portales no escriben la clave del SAT sino el nombre ("Factura",
# "NotaCredito", "Recibo de Nomina"). Sin esto, "NotaCredito" -> "N" -> nomina.
PATRONES_TIPO = (
    ("E", ("nota de credito", "notacredito", "nota credito", "notas de credito",
           "egreso", "devolucion", "bonificacion", "nota credito egreso")),
    ("P", ("complemento de pago", "complementopago", "recibo electronico de pago",
           "recibo de pago", "complemento", "rep", "pago")),
    ("N", ("recibo de nomina", "recibodenomina", "nomina")),
    ("T", ("traslado", "carta porte", "cartaporte")),
    ("I", ("comprobante de ingreso", "ingreso", "factura", "venta")),
)


def clasificar_tipo(valor: Any) -> str:
    """
    Devuelve la clave del SAT (I/E/N/P/T) a partir de la clave o del texto.
      'I - Ingreso'   -> 'I'      'NotaCredito' -> 'E'
      'Factura'       -> 'I'      'Nota de Credito' -> 'E'
    """
    clave = limpiar_clave(valor)
    if clave in ("I", "E", "N", "P", "T"):
        return clave
    texto = normalizar(valor)
    if not texto:
        return ""
    for letra, patrones in PATRONES_TIPO:
        for patron in patrones:
            # Los patrones cortos ('rep') exigen palabra completa para no pegar
            # con 'reporte' o 'representante'.
            if len(patron) <= 3:
                if re.search(rf"(?<![a-z0-9]){re.escape(patron)}(?![a-z0-9])", texto):
                    return letra
            elif patron in texto:
                return letra
    return clave[:1] if clave[:1] in ("I", "E", "N", "P", "T") else ""


# --- Tipo de archivo que subio el contador -----------------------------------
ETIQUETAS_ORIGEN = {
    "EMITIDAS": "Emitidas", "RECIBIDAS": "Recibidas", "EGRESOS": "Egresos",
    "PAGOS": "Pagos", "NOMINAS": "Nominas", "OTROS": "Otros",
}
ORDEN_ORIGENES = ["EMITIDAS", "RECIBIDAS", "EGRESOS", "PAGOS", "NOMINAS", "OTROS"]

# El orden importa: 'Complemento de pagos recibidos' es PAGOS, no RECIBIDAS.
PISTAS_ORIGEN = (
    ("NOMINAS", ("nomina", "nominas", "payroll", "raya")),
    ("EMITIDAS", ("emitida", "emitidas", "emitido", "emitidos", "emision",
                  "facturacion", "ventas", "ingresos")),
    ("EGRESOS", ("egreso", "egresos")),
    ("PAGOS", ("pago", "pagos", "rep", "complemento", "complementos")),
    ("RECIBIDAS", ("recibida", "recibidas", "recibido", "recibidos", "compras",
                   "proveedores", "gastos", "deduccion", "deducciones")),
)


def detectar_origen(nombre_archivo: str, df: Optional[pd.DataFrame] = None,
                    forzado: Optional[str] = None,
                    nombre_hoja: Optional[str] = None) -> Tuple[str, str]:
    """
    Decide que es cada bloque de CFDI: primero por el nombre de la hoja, luego
    por el del archivo y, si nada alcanza, por el tipo que domina adentro.
    Devuelve (ORIGEN, como_se_decidio).
    """
    if forzado and str(forzado).upper() in ETIQUETAS_ORIGEN:
        return str(forzado).upper(), "config"

    for texto, como in ((nombre_hoja, "nombre de la hoja"),
                        (nombre_archivo, "nombre del archivo")):
        if not texto:
            continue
        n = normalizar(texto)
        for origen, pistas in PISTAS_ORIGEN:
            for pista in pistas:
                if re.search(rf"(?<![a-z0-9]){re.escape(pista)}(?![a-z0-9])", n):
                    return origen, como

    if df is not None and not df.empty and "Tipo Comprobante" in df.columns:
        tipos = df["Tipo Comprobante"].apply(clasificar_tipo)
        conteo = tipos[tipos != ""].value_counts()
        if not conteo.empty:
            dominante = str(conteo.index[0])
            if dominante == "N":
                return "NOMINAS", "contenido"
            if dominante == "P":
                return "PAGOS", "contenido"
            if dominante == "E":
                return "EGRESOS", "contenido"
    return "RECIBIDAS", "contenido"


def _limpiar_moneda(valor: Any) -> str:
    """'MXN - Peso Mexicano', 'Pesos', 'Dolar americano' -> codigo ISO. Vacio -> MXN."""
    n = normalizar(valor)
    if not n:
        return "MXN"
    clave = limpiar_clave(valor)[:3]
    if clave in MONEDAS_ISO:
        return clave
    for fragmento, codigo in (("peso", "MXN"), ("mexican", "MXN"), ("mxn", "MXN"),
                              ("dolar", "USD"), ("dollar", "USD"), ("usd", "USD"),
                              ("euro", "EUR"), ("eur", "EUR"), ("libra", "GBP"),
                              ("yen", "JPY"), ("canadien", "CAD"), ("franco", "CHF")):
        if fragmento in n:
            return codigo
    return clave or "MXN"


# =============================================================================
# 3. ANALISIS DE COLOR ("OJOS DE CONTADOR")
# =============================================================================

# Paleta indexada clasica de Excel donde el indice significa rojo
INDICES_ROJOS = {3, 10}


def _rgb_es_rojo(rgb: Optional[str], heuristica: bool, paleta: List[str]) -> bool:
    """True si el hex ARGB/RGB corresponde a un rojo (exacto o por heuristica)."""
    if not rgb or not isinstance(rgb, str):
        return False
    hexa = rgb.upper().strip()
    if hexa in {p.upper() for p in paleta}:
        return True
    hexa = hexa[-6:] if len(hexa) >= 6 else hexa
    if len(hexa) != 6 or not re.fullmatch(r"[0-9A-F]{6}", hexa):
        return False
    if not heuristica:
        return False
    r, g, b = int(hexa[0:2], 16), int(hexa[2:4], 16), int(hexa[4:6], 16)
    # Rojo dominante: componente roja alta y muy por encima de verde y azul.
    return r >= 110 and r >= g * 2 and r >= b * 2


def _color_es_rojo(color, heuristica: bool, paleta: List[str]) -> bool:
    if color is None:
        return False
    try:
        if getattr(color, "type", None) == "indexed" and color.indexed in INDICES_ROJOS:
            return True
        return _rgb_es_rojo(getattr(color, "rgb", None), heuristica, paleta)
    except Exception:
        return False


def _relleno_es_rojo(celda, heuristica: bool, paleta: List[str]) -> bool:
    relleno = celda.fill
    if relleno is None or relleno.fill_type in (None, "none"):
        return False
    # Rellenos "Incorrecto" de Excel: FFC7CE (rosa) y similares.
    for color in (relleno.start_color, relleno.fgColor):
        if color is None:
            continue
        rgb = getattr(color, "rgb", None)
        if not isinstance(rgb, str):
            continue
        hexa = rgb.upper()[-6:]
        if hexa in {p.upper()[-6:] for p in paleta}:
            return True
        if heuristica and re.fullmatch(r"[0-9A-F]{6}", hexa):
            r, g, b = int(hexa[0:2], 16), int(hexa[2:4], 16), int(hexa[4:6], 16)
            if r >= 180 and r > g + 25 and r > b + 25:   # rosados tipo FFC7CE
                return True
    return False


# =============================================================================
# 4. LECTURA INTELIGENTE DEL EXCEL
# =============================================================================

def leer_hojas_excel(ruta: str, config: Optional[Dict[str, Any]] = None
                     ) -> List[Tuple[pd.DataFrame, Dict[str, Any]]]:
    """
    Lee TODAS las hojas con datos de un Excel y devuelve una por una.

    Un archivo del portal contable suele traer varias hojas que son cosas
    distintas ('Deducciones autorizadas', 'Complementos de pago',
    'Nomina pagada'). Quedarse con una sola tira el resto del trabajo.
    """
    cfg = config or cargar_config()
    ext = os.path.splitext(ruta)[1].lower()

    if ext in (".csv", ".txt") or not OPENPYXL_OK or ext == ".xls":
        df, diag = leer_excel_inteligente(ruta, cfg)
        return [(df, diag)] if not df.empty else []

    wb = load_workbook(ruta, data_only=True)
    minimo = int(cfg.get("puntaje_minimo_hoja", 6))
    salida: List[Tuple[pd.DataFrame, Dict[str, Any]]] = []

    for hoja in wb.worksheets:
        filas_tope = []
        for i, fila in enumerate(hoja.iter_rows(values_only=True)):
            filas_tope.append(list(fila))
            if i >= int(cfg.get("filas_a_escanear_encabezado", 30)):
                break
        if not filas_tope:
            continue
        fila_enc, puntaje = _buscar_fila_encabezado(filas_tope, cfg, devolver_puntaje=True)
        if puntaje < minimo:
            continue   # catalogos, notas, hojas de ayuda: no son datos de CFDI
        df, diag = _leer_una_hoja(hoja, fila_enc, ruta, cfg)
        if not df.empty:
            salida.append((df, diag))

    if not salida:   # ninguna hoja puntuo: se intenta con la mejor, como antes
        df, diag = leer_excel_inteligente(ruta, cfg)
        if not df.empty:
            salida.append((df, diag))
    return salida


def leer_excel_inteligente(ruta: str, config: Optional[Dict[str, Any]] = None
                           ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Lee un Excel crudo del SAT / portal contable:
      * localiza la fila real de encabezados saltando la basura superior,
      * mapea columnas a nombres canonicos,
      * inyecta las banderas de formato _Es_Rojo, _Es_Rojo_Fuente, _Es_Rojo_Relleno.

    Devuelve (DataFrame, diagnostico) de UNA hoja (la que mejor puntua).
    """
    cfg = config or cargar_config()
    diag: Dict[str, Any] = {
        "archivo": os.path.basename(ruta),
        "hoja": None,
        "fila_encabezado": None,
        "columnas_detectadas": {},
        "columnas_ignoradas": [],
        "filas_rojas": 0,
        "avisos": [],
    }
    ext = os.path.splitext(ruta)[1].lower()

    if ext in (".csv", ".txt"):
        df = _leer_csv_inteligente(ruta, cfg, diag)
        df["_Es_Rojo_Fuente"] = False
        df["_Es_Rojo_Relleno"] = False
        df["_Es_Rojo"] = False
        diag["avisos"].append("CSV sin formato: no hay analisis de color disponible.")
        return df, diag

    if not OPENPYXL_OK or ext == ".xls":
        # .xls antiguo: pandas/xlrd, sin metadatos de color
        df = pd.read_excel(ruta, header=None)
        fila = _buscar_fila_encabezado(df.values.tolist(), cfg)
        df = _armar_dataframe(df.values.tolist(), fila, diag)
        df["_Es_Rojo_Fuente"] = False
        df["_Es_Rojo_Relleno"] = False
        df["_Es_Rojo"] = False
        diag["fila_encabezado"] = fila + 1
        diag["avisos"].append("Formato .xls: sin analisis de color (convierte a .xlsx).")
        return df, diag

    wb = load_workbook(ruta, data_only=True)
    hoja, fila_enc = _elegir_hoja(wb, cfg)
    return _leer_una_hoja(hoja, fila_enc, ruta, cfg)


def _leer_una_hoja(hoja, fila_enc: int, ruta: str, cfg: Dict[str, Any]
                   ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Convierte una hoja de calculo en DataFrame + diagnostico."""
    diag: Dict[str, Any] = {
        "archivo": os.path.basename(ruta),
        "hoja": hoja.title.strip(),
        "fila_encabezado": fila_enc + 1,   # 1-based para el humano
        "columnas_detectadas": {},
        "columnas_ignoradas": [],
        "filas_rojas": 0,
        "avisos": [],
    }

    filas = [[c.value for c in fila] for fila in hoja.iter_rows()]
    df = _armar_dataframe(filas, fila_enc, diag)

    # --- Analisis de color alineado por indice de fila fisica --------------
    heur = bool(cfg.get("detectar_rojo_por_heuristica", True))
    paleta = list(cfg.get("colores_nota_credito", []))
    ver_relleno = bool(cfg.get("detectar_relleno_rojo", True))
    cols_clave = set(cfg.get("columnas_clave_para_color", []))

    # indices (0-based dentro de la fila) de las columnas clave
    mapa = mapear_columnas(filas[fila_enc])
    idx_clave = [i for i, canon in mapa.items() if canon in cols_clave] or list(mapa.keys())

    rojo_fuente, rojo_relleno = [], []
    for fila_fisica in range(fila_enc + 2, hoja.max_row + 1):  # openpyxl es 1-based
        rf = rr = False
        for i in idx_clave:
            celda = hoja.cell(row=fila_fisica, column=i + 1)
            if celda.value is None:
                continue
            if not rf and celda.font is not None and _color_es_rojo(celda.font.color, heur, paleta):
                rf = True
            if ver_relleno and not rr and _relleno_es_rojo(celda, heur, paleta):
                rr = True
            if rf and rr:
                break
        rojo_fuente.append(rf)
        rojo_relleno.append(rr)

    n = len(df)
    df["_Es_Rojo_Fuente"] = (rojo_fuente + [False] * n)[:n]
    df["_Es_Rojo_Relleno"] = (rojo_relleno + [False] * n)[:n]
    df["_Es_Rojo"] = df["_Es_Rojo_Fuente"] | df["_Es_Rojo_Relleno"]
    diag["filas_rojas"] = int(df["_Es_Rojo"].sum())
    return df, diag


def _leer_csv_inteligente(ruta: str, cfg: Dict[str, Any], diag: Dict[str, Any]) -> pd.DataFrame:
    for sep in (",", ";", "\t", "|"):
        try:
            crudo = pd.read_csv(ruta, header=None, sep=sep, dtype=object,
                                encoding="utf-8-sig", engine="python")
        except Exception:
            continue
        if crudo.shape[1] > 1:
            filas = crudo.values.tolist()
            fila = _buscar_fila_encabezado(filas, cfg)
            diag["fila_encabezado"] = fila + 1
            return _armar_dataframe(filas, fila, diag)
    raise ValueError(f"No se pudo interpretar el archivo CSV: {os.path.basename(ruta)}")


def _elegir_hoja(wb, cfg: Dict[str, Any]):
    """Elige la hoja cuya fila de encabezados puntua mas alto."""
    mejor = (None, 0, -1)  # (hoja, fila, puntaje)
    for hoja in wb.worksheets:
        filas = []
        for i, fila in enumerate(hoja.iter_rows(values_only=True)):
            filas.append(list(fila))
            if i >= int(cfg.get("filas_a_escanear_encabezado", 30)):
                break
        if not filas:
            continue
        idx, puntaje = _buscar_fila_encabezado(filas, cfg, devolver_puntaje=True)
        if puntaje > mejor[2]:
            mejor = (hoja, idx, puntaje)
    if mejor[0] is None:
        return wb.worksheets[0], 0
    return mejor[0], mejor[1]


def _buscar_fila_encabezado(filas: List[List[Any]], cfg: Dict[str, Any],
                            devolver_puntaje: bool = False):
    """Itera las primeras filas buscando la que mas parezca encabezado real."""
    limite = min(len(filas), int(cfg.get("filas_a_escanear_encabezado", 30)))
    mejor_idx, mejor_pts = 0, -1
    for i in range(limite):
        pts = _puntuar_fila_encabezado(filas[i])
        if pts > mejor_pts:
            mejor_idx, mejor_pts = i, pts
    if mejor_pts < 4:           # nada parecido: asumimos fila 0
        mejor_idx = 0
    return (mejor_idx, mejor_pts) if devolver_puntaje else mejor_idx


def _armar_dataframe(filas: List[List[Any]], fila_enc: int, diag: Dict[str, Any]) -> pd.DataFrame:
    encabezados = filas[fila_enc] if fila_enc < len(filas) else []
    mapa = mapear_columnas(encabezados)
    diag["columnas_detectadas"] = {str(encabezados[i]): canon for i, canon in mapa.items()
                                   if i < len(encabezados)}
    diag["columnas_ignoradas"] = [str(h) for i, h in enumerate(encabezados)
                                  if i not in mapa and h not in (None, "")]

    datos = filas[fila_enc + 1:]
    registros = []
    for fila in datos:
        reg = {canon: (fila[i] if i < len(fila) else None) for i, canon in mapa.items()}
        # columnas extra que no reconocimos se conservan con su nombre original
        for i, h in enumerate(encabezados):
            if i in mapa or h in (None, ""):
                continue
            reg[str(h).strip()] = fila[i] if i < len(fila) else None
        registros.append(reg)

    df = pd.DataFrame(registros)
    if df.empty:
        return df
    # Fuera filas vacias y pies de pagina (sumatorias que el contador deja
    # al final de la hoja, sin UUID ni RFC pero con importes).
    df = df.dropna(how="all")

    identidad = [c for c in ("UUID", "RFC Emisor", "RFC Receptor", "Fecha Emision")
                 if c in df.columns]
    if identidad:
        antes = len(df)
        tiene_id = None
        for col in identidad:
            # OJO: en pandas 3 .astype(str) NO convierte NaN a 'nan', hay que
            # rellenar antes o el filtro no detecta nada.
            texto = df[col].where(df[col].notna(), "").astype(str).str.strip().str.lower()
            valido = ~texto.isin(BASURA_IDENTIDAD)
            tiene_id = valido if tiene_id is None else (tiene_id | valido)
        df = df[tiene_id]
        if len(df) < antes:
            diag.setdefault("avisos", []).append(
                f"Se descartaron {antes - len(df)} renglones sin UUID ni RFC: "
                f"son pies de pagina o sumatorias de la hoja, no comprobantes.")
    return df.reset_index(drop=True)


# =============================================================================
# 5. PREPARACION / LIMPIEZA DEL DATAFRAME
# =============================================================================

# Valores que NO identifican a un comprobante: delatan un renglon de sumatoria
BASURA_IDENTIDAD = {"", "nan", "none", "nat", "total", "total general", "totales",
                    "suma", "sumas", "subtotal", "igual", "mas", "menos",
                    "(igual)", "(mas)", "(menos)", "-", "--"}

COLUMNAS_MINIMAS = ["UUID", "RFC Emisor", "Nombre Emisor", "RFC Receptor", "Nombre Receptor",
                    "Fecha Emision", "Tipo Comprobante", "Uso CFDI", "Forma Pago",
                    "Metodo Pago", "Descripcion", "Moneda", "Subtotal", "Descuento",
                    "IVA", "IVA Tasa 8", "IEPS", "Total Trasladados",
                    "Base 16", "Base 8", "Base 0", "Base Exento",
                    "Base Sin Clasificar", "IVA Retenido",
                    "ISR Retenido", "IEPS Retenido", "Retenciones",
                    "Percepciones", "Deducciones", "Otros Pagos",
                    "Total", "Monto Pagado", "Estatus"]

# Todas las columnas de dinero que el sistema analiza, convierte a MXN y totaliza.
COLUMNAS_IMPORTE = ["Subtotal", "Descuento", "IVA", "IVA Tasa 8", "IEPS",
                    "Total Trasladados", "Base 16", "Base 8", "Base 0",
                    "Base Exento", "Base Sin Clasificar",
                    "IVA Retenido", "ISR Retenido", "IEPS Retenido", "Retenciones",
                    "Percepciones", "Deducciones", "Otros Pagos",
                    "Total", "Monto Pagado"]


_ISO = re.compile(r"^\s*\d{4}-\d{2}-\d{2}")


def _parsear_fechas(serie: pd.Series) -> pd.Series:
    """
    Convierte la columna de fechas respetando el formato de cada valor.

    OJO: el XML del SAT trae '2026-08-07T13:19:44'. Parsear eso con dayfirst=True
    lo vuelve 8 de JULIO, porque pandas lee '08-07' como dia-mes. Por eso las
    fechas ISO se parsean aparte, y solo el resto (dd/mm/aaaa de los portales)
    usa dayfirst.
    """
    texto = serie.astype(str)
    es_iso = texto.str.match(_ISO).fillna(False)

    salida = pd.Series(pd.NaT, index=serie.index, dtype="datetime64[ns]")
    if es_iso.any():
        salida.loc[es_iso] = pd.to_datetime(serie[es_iso], errors="coerce",
                                            format="mixed", dayfirst=False)
    if (~es_iso).any():
        salida.loc[~es_iso] = pd.to_datetime(serie[~es_iso], errors="coerce",
                                             dayfirst=True)
    return salida


def preparar_dataframe(df: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
    """Normaliza claves, importes e impuestos, y aplica el override de color."""
    if df.empty:
        return df
    df = df.copy()
    for col in COLUMNAS_MINIMAS:
        if col not in df.columns:
            df[col] = None
    if "Origen" not in df.columns:
        df["Origen"] = "RECIBIDAS"
    # Columnas que solo existen cuando la fuente es XML
    for col, defecto in (("Claves ProdServ", ""), ("UUID Relacionados", ""),
                         ("Tipo Cambio CFDI", 0.0), ("Serie", ""), ("Folio", ""),
                         ("Version CFDI", ""), ("Regimen Emisor", ""),
                         ("Regimen Receptor", ""), ("Archivo XML", ""),
                         ("Tipo Relacion", ""), ("CFDI Relacionados", ""),
                         ("UUID Sustituidos", ""), ("CP Receptor", ""),
                         ("Factura Global", False),
                         ("Estatus SAT Consulta", ""), ("Cancelacion SAT", ""),
                         ("EFOS SAT", ""), ("Es Cancelable", "")):
        if col not in df.columns:
            df[col] = defecto
    for bandera in ("_Es_Rojo", "_Es_Rojo_Fuente", "_Es_Rojo_Relleno"):
        if bandera not in df.columns:
            df[bandera] = False
        df[bandera] = df[bandera].fillna(False).astype(bool)

    # --- Claves oficiales -------------------------------------------------
    df["Tipo Comprobante"] = df["Tipo Comprobante"].apply(clasificar_tipo)
    df["Forma Pago"] = df["Forma Pago"].apply(lambda v: limpiar_clave(v, longitud=2))
    df["Metodo Pago"] = df["Metodo Pago"].apply(_limpiar_metodo_pago)
    df["Uso CFDI"] = df["Uso CFDI"].apply(lambda v: limpiar_clave(v)[:4])
    df["Moneda"] = df["Moneda"].apply(_limpiar_moneda)

    # --- Importes ---------------------------------------------------------
    for col in COLUMNAS_IMPORTE:
        df[col] = df[col].apply(a_numero)

    # --- Fecha ------------------------------------------------------------
    df["Fecha Emision"] = _parsear_fechas(df["Fecha Emision"])

    # --- Texto ------------------------------------------------------------
    df["Descripcion"] = df["Descripcion"].fillna("").astype(str)
    df["_Descripcion_Norm"] = df["Descripcion"].apply(normalizar)
    for col in ("RFC Emisor", "RFC Receptor"):
        df[col] = df[col].fillna("").astype(str).str.strip().str.upper()

    # --- Override por color: rojo => Nota de Credito (E) ------------------
    df["_Tipo_Original"] = df["Tipo Comprobante"]
    df["_Forzado_Por_Color"] = False

    sin_tipo = df["Tipo Comprobante"] == ""
    rojo_sin_tipo = df["_Es_Rojo"] & sin_tipo
    df.loc[rojo_sin_tipo, "Tipo Comprobante"] = "E"
    df.loc[rojo_sin_tipo, "_Forzado_Por_Color"] = True

    # Rojo CON tipo declarado "I": no se toca el importe, se manda a Revisar.
    df["_Conflicto_Color"] = df["_Es_Rojo"] & (df["_Tipo_Original"] == "I")

    if config.get("tratar_total_negativo_como_egreso", True):
        negativos = (df["Total"] < 0) & (df["Tipo Comprobante"].isin(["", "I"]))
        df.loc[negativos, "Tipo Comprobante"] = "E"

    # Hay hojas (nomina, complementos de pago) que no traen columna de tipo:
    # el tipo lo dice la hoja misma.
    falta_tipo = df["Tipo Comprobante"] == ""
    df.loc[falta_tipo & (df["Origen"] == "NOMINAS"), "Tipo Comprobante"] = "N"
    df.loc[falta_tipo & (df["Origen"] == "PAGOS"), "Tipo Comprobante"] = "P"

    # Sin tipo y sin color: se asume Ingreso (una factura de gasto normal)
    df.loc[df["Tipo Comprobante"] == "", "Tipo Comprobante"] = "I"

    # Los importes se manejan en positivo; el signo lo pone la regla, no el dato.
    for col in COLUMNAS_IMPORTE:
        df[col] = df[col].abs()

    # --- Reconstruccion de los importes que el portal no trajo ------------
    # CFDI: Total = Subtotal - Descuento + (IVA + IEPS) - Retenciones
    es_gasto = df["Tipo Comprobante"].isin(["I", "E"])

    # Total de retenciones a partir del desglose (o al reves no: el desglose
    # no se puede inventar desde el total).
    desglose_ret = df["IVA Retenido"] + df["ISR Retenido"] + df["IEPS Retenido"]
    falta_ret = (df["Retenciones"] == 0) & (desglose_ret > 0)
    df.loc[falta_ret, "Retenciones"] = desglose_ret[falta_ret]

    # Si el portal trajo el total de traslados pero no el IVA, se separa el IEPS
    falta_iva_trasl = (df["IVA"] == 0) & (df["Total Trasladados"] > 0)
    df.loc[falta_iva_trasl, "IVA"] = (df["Total Trasladados"] - df["IEPS"]
                                      ).clip(lower=0)[falta_iva_trasl]

    falta_sub = es_gasto & (df["Subtotal"] == 0) & (df["Total"] > 0)
    falta_iva_orig = es_gasto & (df["IVA"] == 0) & (df["IEPS"] == 0)

    # Cuando el archivo no trae NI subtotal NI impuestos solo se conoce el Total:
    # el sistema no inventa el desglose, lo marca. Si en config_reglas.json pones
    # "iva_por_defecto": 0.16, lo separa asumiendo esa tasa.
    ambos_faltan = falta_sub & falta_iva_orig
    tasa_defecto = float(config.get("iva_por_defecto", 0) or 0)
    if ambos_faltan.any() and tasa_defecto > 0:
        df.loc[ambos_faltan, "Subtotal"] = (df["Total"] / (1 + tasa_defecto)).round(2)
        df.loc[ambos_faltan, "IVA"] = (df["Total"] - df["Subtotal"]).round(2)
        df.loc[ambos_faltan, "_IVA_Calculado"] = True
        falta_sub = falta_sub & ~ambos_faltan
    df["_Importes_Incompletos"] = ambos_faltan & (tasa_defecto <= 0)

    if falta_sub.any():
        df.loc[falta_sub, "Subtotal"] = (df["Total"] - df["IVA"] - df["IEPS"]
                                         + df["Retenciones"] + df["Descuento"]
                                         ).clip(lower=0).round(2)

    falta_iva = es_gasto & (df["IVA"] == 0) & (df["Subtotal"] > 0) & (df["Total"] > 0)
    if falta_iva.any():
        traslados = (df["Total"] - df["Subtotal"] + df["Descuento"]
                     + df["Retenciones"] - df["IEPS"]).round(2)
        # Solo se acepta como IVA si es una cifra creible (evita ruido por redondeo)
        creible = falta_iva & (traslados > 0.5) & (traslados <= df["Subtotal"] * 0.30)
        df.loc[creible, "IVA"] = traslados[creible]
        df.loc[creible, "_IVA_Calculado"] = True

    for bandera in ("_IVA_Calculado", "_Importes_Incompletos"):
        if bandera not in df.columns:
            df[bandera] = False
        df[bandera] = df[bandera].fillna(False).astype(bool)

    # Nomina: percepciones / deducciones se completan entre si
    es_nomina = df["Tipo Comprobante"] == "N"
    falta_perc = es_nomina & (df["Percepciones"] == 0) & (df["Subtotal"] > 0)
    df.loc[falta_perc, "Percepciones"] = df.loc[falta_perc, "Subtotal"]
    falta_ded = es_nomina & (df["Deducciones"] == 0) & (df["Percepciones"] > 0) \
        & (df["Total"] > 0)
    if falta_ded.any():
        df.loc[falta_ded, "Deducciones"] = (df["Percepciones"] + df["Otros Pagos"]
                                            - df["Total"]).clip(lower=0).round(2)

    # --- Bases por tasa de IVA -------------------------------------------
    # Si el portal no las trajo, se deducen de lo que si vino. Lo que no se
    # pueda clasificar queda a la vista en "Base Sin Clasificar": no se
    # reparte a ciegas entre tasa 0 y exento, porque no es lo mismo.
    bases = df["Base 16"] + df["Base 8"] + df["Base 0"] + df["Base Exento"]
    # La nomina no tiene base de IVA: su gasto son las percepciones.
    falta_base = (bases == 0) & (df["Subtotal"] > 0) & (df["Tipo Comprobante"] != "N")
    con_iva = falta_base & (df["IVA"] > 0)
    df.loc[con_iva, "Base 16"] = df.loc[con_iva, "Subtotal"]
    con_iva8 = falta_base & (df["IVA"] == 0) & (df["IVA Tasa 8"] > 0)
    df.loc[con_iva8, "Base 8"] = df.loc[con_iva8, "Subtotal"]
    sin_iva = falta_base & (df["IVA"] == 0) & (df["IVA Tasa 8"] == 0)
    df.loc[sin_iva, "Base Sin Clasificar"] = df.loc[sin_iva, "Subtotal"]

    # Complemento de pago sin "Monto Pagado" mapeado: usa el Total
    sin_monto = (df["Tipo Comprobante"] == "P") & (df["Monto Pagado"] == 0)
    df.loc[sin_monto, "Monto Pagado"] = df.loc[sin_monto, "Total"]

    # --- Etiquetas legibles del catalogo SAT ------------------------------
    df["Tipo Comprobante Desc"] = df["Tipo Comprobante"].map(TIPOS_COMPROBANTE).fillna("")
    df["Forma Pago Desc"] = df["Forma Pago"].map(FORMAS_PAGO).fillna("")
    df["Metodo Pago Desc"] = df["Metodo Pago"].map(METODOS_PAGO).fillna("")
    df["Uso CFDI Desc"] = df["Uso CFDI"].map(USOS_CFDI).fillna("")

    return df


def _limpiar_metodo_pago(valor: Any) -> str:
    n = normalizar(valor)
    if "ppd" in n or "parcialidades" in n or "diferido" in n:
        return "PPD"
    if "pue" in n or "una exhibicion" in n or "una sola exhibicion" in n:
        return "PUE"
    return limpiar_clave(valor)[:3]


# =============================================================================
# 6. REGLAS DE NEGOCIO POR TIPO DE ARCHIVO
# =============================================================================

MOTIVOS = {
    1: "Regla 1 - Pago en efectivo (01) por {monto} >= {tope}. No deducible (Art. 27 F-III LISR).",
    2: "Regla 2 - Timbrada PPD: no acumula/deduce aqui, se refleja con su REP (complemento de pago).",
    3: "Regla 3 - Nota de credito: se informa pero NO entra en la sumatoria.",
    4: "Regla 4 - Concepto no deducible: {palabra}.",
    "personal": "Deduccion PERSONAL (uso {uso} - {desc}). No es deduccion autorizada "
                "de la actividad: va en la declaracion anual, con sus propios topes.",
    "combustible": "Combustible pagado con '{forma}'. El Art. 27 F-III LISR exige "
                   "medios bancarios para combustible SIN IMPORTAR EL MONTO.",
    "cancelado": "Comprobante cancelado ante el SAT.",
    "sin_tipo": "No se pudo determinar el tipo de comprobante. Revisar manualmente.",
}
MOTIVOS.update(reglas_md.MOTIVOS_MD)

# Que importe representa a cada comprobante dentro de su bloque
def _importe_base(fila: pd.Series, config: Dict[str, Any]) -> float:
    tipo = fila["Tipo Comprobante"]
    if tipo == "P":
        pagado = float(fila.get("Monto Pagado") or 0)
        return pagado if pagado else float(fila.get("Total") or 0)
    if tipo == "N" and str(config.get("nomina_suma", "percepciones")).lower() == "percepciones":
        # El gasto del patron es el total de percepciones, no el neto depositado:
        # el ISR retenido tambien es parte de la erogacion. Cambialo con
        # "nomina_suma": "total" en config_reglas.json.
        percepciones = float(fila.get("Percepciones") or 0)
        if percepciones:
            return percepciones + float(fila.get("Otros Pagos") or 0)
    return float(fila.get("Total") or 0)


def aplicar_reglas(df: pd.DataFrame, config: Dict[str, Any]) -> pd.DataFrame:
    """
    Evalua cada CFDI segun el archivo del que vino (Origen) y marca:
      _Aceptado          -> paso las reglas (no fue rechazado)
      _Suma              -> entra en la sumatoria de su bloque
      Importe Computado  -> el monto exacto que se suma (0 si no suma)
      Clasificacion / Regla Aplicada / Motivo de Rechazo
    """
    if df.empty:
        return df
    df = df.copy()

    tope = float(config.get("tope_efectivo", 2000.0))
    lista_negra = [normalizar(p) for p in config.get("lista_negra", []) if normalizar(p)]
    frases = [normalizar(p) for p in config.get("lista_negra_frases", []) if normalizar(p)]
    exentos = {r.strip().upper() for r in config.get("rfc_exentos_lista_negra", [])}
    tope_a_egresos = bool(config.get("aplicar_tope_efectivo_a_egresos", False))
    tope_a_nomina = bool(config.get("aplicar_tope_efectivo_a_nomina", False))
    negra_a_todos = bool(config.get("aplicar_lista_negra_a_nomina_y_pagos", False))
    claves_negras = {str(c).strip() for c in
                     config.get("claves_prodserv_no_deducibles", []) if str(c).strip()}
    separar_personales = bool(config.get("separar_deducciones_personales", True))
    usos_personales = {str(u).strip().upper()
                       for u in config.get("usos_deduccion_personal", []) if str(u).strip()}
    exigir_banco_combustible = bool(config.get("combustible_solo_medios_bancarios", True))
    formas_bancarias = {str(f).strip().zfill(2)
                        for f in config.get("formas_pago_bancarias", []) if str(f).strip()}
    claves_combustible = tuple(str(c).strip() for c in
                               config.get("claves_prodserv_combustible", []) if str(c).strip())
    palabras_combustible = [normalizar(p) for p in
                            config.get("palabras_combustible", []) if normalizar(p)]
    modo_nc = str(config.get("notas_credito", "excluir")).lower()
    ctx = reglas_md.construir_contexto(config, os.path.dirname(os.path.abspath(__file__)))

    aceptado, suma, importe, base_all, motivo, clasif, regla = [], [], [], [], [], [], []
    iva_acred, alerta_txt = [], []

    for _, f in df.iterrows():
        origen = str(f.get("Origen") or "RECIBIDAS").upper()
        tipo = f["Tipo Comprobante"]
        total = float(f["Total"] or 0)
        base = _importe_base(f, config)
        ok, sm, mot, cls, rg = True, True, "", "", ""
        factor = 1.0          # parte del importe que se deduce (restaurantes: 8.5 %)
        iva_especial = None   # IVA acreditable cuando no sigue a la suma (inversiones)

        # ---- Estatus SAT: un CFDI cancelado nunca cuenta -----------------
        estatus = normalizar(f.get("Estatus"))
        cancelado = (estatus.startswith("cancel") and "cancelable" not in estatus) \
            or estatus in ("no vigente", "cancelada", "cancelado")
        if cancelado:
            ok, sm = False, False
            mot, cls, rg = MOTIVOS["cancelado"], "Cancelado", "Estatus SAT"

        # ---- Sustituida (relacion 04): solo cuenta la factura nueva --------
        elif bool(f.get("_Sustituido", False)):
            sm = False
            mot, cls, rg = MOTIVOS["sustituida"], "Sustituida (no suma)", "Sustitucion"

        # ---- Notas de credito: se informan pero no suman (en TODO archivo)
        elif tipo == "E":
            sm = (modo_nc == "restar")
            cls = ("Nota de Credito (resta)" if sm else "Nota de Credito (no suma)")
            rg = "Regla 3"
            if not sm:
                mot = MOTIVOS[3]
            base = -base if sm else base
            if sm and origen in ("RECIBIDAS", "EGRESOS"):
                iva_especial = -float(f.get("IVA") or 0)   # reduce el IVA acreditable (LIVA 7)

        # ---- EMITIDAS: ingresos facturados por el cliente -----------------
        elif origen == "EMITIDAS":
            if tipo == "P":
                cls, rg = "REP emitido (suma)", "Regla 6"
            elif f["Metodo Pago"] == "PPD":
                sm, mot, cls, rg = False, MOTIVOS[2], "PPD timbrada (no suma)", "Regla 2"
            else:
                cls, rg = "Ingreso PUE (suma)", "Regla 2"

        # ---- PAGOS: complementos de pago (REP) ---------------------------
        elif origen == "PAGOS":
            if f["Forma Pago"] == "01" and base >= tope:
                ok, sm = False, False
                mot = MOTIVOS[1].format(monto=f"${base:,.2f}", tope=f"${tope:,.2f}")
                cls, rg = "Rechazado", "Regla 1"
            else:
                etiqueta = FORMAS_PAGO.get(f["Forma Pago"], "Forma no especificada")
                cls, rg = f"Pago: {etiqueta}", "Regla 6"

        # ---- NOMINAS -----------------------------------------------------
        elif origen == "NOMINAS":
            if tope_a_nomina and f["Forma Pago"] == "01" and total >= tope:
                ok, sm = False, False
                mot = MOTIVOS[1].format(monto=f"${total:,.2f}", tope=f"${tope:,.2f}")
                cls, rg = "Rechazado", "Regla 1"
            else:
                cls, rg = "Nomina (suma)", "Regla 5"

        # ---- Deduccion PERSONAL: no es deduccion autorizada ---------------
        elif separar_personales and _es_deduccion_personal(f, usos_personales):
            uso = str(f.get("Uso CFDI") or "").upper()
            sm = False
            mot = MOTIVOS["personal"].format(uso=uso, desc=USOS_CFDI.get(uso, "personal"))
            cls, rg = "Deduccion personal (no suma)", "Deduccion personal"

        # ---- RECIBIDAS / EGRESOS: los gastos deducibles -------------------
        else:
            forma_desc = FORMAS_PAGO.get(f["Forma Pago"], f["Forma Pago"] or "sin especificar")
            # El combustible se juzga solo cuando la forma de pago ya se conoce.
            # En una PPD (o con forma '99 - Por definir') se define hasta el REP.
            forma_conocida = f["Forma Pago"] not in ("", "99")
            es_combustible = (forma_conocida and f["Metodo Pago"] != "PPD"
                              and _es_combustible(f, claves_combustible,
                                                  palabras_combustible))
            formal = reglas_md.rechazo_formal(f, ctx) if tipo in ("I", "E") else None
            inv = reglas_md.inversion(f, ctx) if tipo == "I" else None
            if formal:
                # Reglas 7-9: forma del CFDI, proveedor 69-B, ejercicio
                ok, sm = False, False
                cls, rg, mot = formal
            elif inv and f["Metodo Pago"] != "PPD" and not (
                    f["Forma Pago"] == "01" and total >= tope):
                # Inversion: no se deduce en el mes, se deprecia. El IVA si se acredita.
                sm = False
                desc_inv, txt_tasa = inv
                mot = MOTIVOS["inversion"].format(uso=str(f.get("Uso CFDI")).upper(),
                                                  desc=desc_inv, tasa=txt_tasa)
                cls, rg = "Inversion (activo fijo, no suma)", "Inversion"
                iva_especial = float(f.get("IVA") or 0)
            elif (exigir_banco_combustible and es_combustible
                    and f["Forma Pago"] not in formas_bancarias):
                ok, sm = False, False
                mot = MOTIVOS["combustible"].format(forma=forma_desc)
                cls, rg = "Rechazado", "Combustible"
            elif f["Forma Pago"] == "01" and total >= tope and (
                    tipo in ("I", "N") or (tipo == "E" and tope_a_egresos)):
                ok, sm = False, False
                mot = MOTIVOS[1].format(monto=f"${total:,.2f}", tope=f"${tope:,.2f}")
                cls, rg = "Rechazado", "Regla 1"
            elif f["Metodo Pago"] == "PPD" and tipo not in ("P", "E", "N"):
                # No es un rechazo: deduce cuando llegue su REP en el archivo de Pagos.
                sm = False
                mot, cls, rg = MOTIVOS[2], "PPD pendiente (no suma)", "Regla 2"
            elif tipo == "I" and f["RFC Emisor"] not in exentos \
                    and reglas_md.es_restaurante(f, ctx):
                # Restaurantes: 8.5 % con tarjeta o monedero; sin ellos, nada (LISR 28-XX)
                if f["Forma Pago"] in ctx.rest_formas:
                    factor = ctx.rest_pct
                    mot = MOTIVOS["restaurante"].format(pct=f"{ctx.rest_pct:.1%}")
                    cls, rg = f"Restaurante ({ctx.rest_pct:.1%} deducible)", "Restaurante"
                else:
                    ok, sm = False, False
                    mot = MOTIVOS["restaurante_forma"].format(forma=forma_desc)
                    cls, rg = "Rechazado", "Restaurante"
            elif (tipo == "I" or negra_a_todos) and f["RFC Emisor"] not in exentos and \
                    _motivo_no_deducible(f, lista_negra, frases, claves_negras):
                motivo_4 = _motivo_no_deducible(f, lista_negra, frases, claves_negras)
                ok, sm = False, False
                mot = MOTIVOS[4].format(palabra=motivo_4)
                cls, rg = "Rechazado", "Regla 4"
            elif tipo == "P":
                cls, rg = "REP recibido (suma)", "Regla 6"
            elif tipo == "N":
                cls, rg = "Nomina (suma)", "Regla 5"
            else:
                cls, rg = "Gasto PUE (suma)", "Regla 2"

        # IVA acreditable: sigue a lo que se deduce (LIVA 5-I). Solo cuenta en lo
        # recibido; una nota de credito lo reduce y una inversion lo conserva.
        if iva_especial is not None:
            iva_row = iva_especial
        elif sm and origen in ("RECIBIDAS", "EGRESOS"):
            iva_row = float(f.get("IVA") or 0) * factor
        else:
            iva_row = 0.0

        aceptado.append(ok)
        suma.append(sm)
        base_all.append(round(abs(base), 2))
        importe.append(round(base * factor, 2) if sm else 0.0)
        iva_acred.append(round(iva_row, 2))
        motivo.append(mot)
        clasif.append(cls)
        regla.append(rg)
        alerta_txt.append("; ".join(reglas_md.alertas(f, ctx)))

    df["_Aceptado"] = aceptado
    df["_Suma"] = suma
    df["Importe Base"] = base_all
    df["Importe Computado"] = importe
    df["IVA Acreditable"] = iva_acred
    df["Alertas"] = alerta_txt
    df["Motivo de Rechazo"] = motivo
    df["Clasificacion"] = clasif
    df["Regla Aplicada"] = regla
    return df


def _es_deduccion_personal(fila: pd.Series, usos_extra: set) -> bool:
    """
    Las deducciones personales (honorarios medicos, colegiaturas, funerales,
    seguros de gastos medicos...) las delata el Uso del CFDI: toda la familia D0*.
    No son deducciones autorizadas de la actividad; van en la anual, con topes.
    """
    uso = str(fila.get("Uso CFDI") or "").strip().upper()
    if not uso:
        return False
    if uso in usos_extra:
        return True
    return bool(re.fullmatch(r"D\d{2}", uso))


def _es_combustible(fila: pd.Series, claves: Tuple[str, ...],
                    palabras: List[str]) -> bool:
    """Por la clave del catalogo SAT si viene (XML), o por la descripcion."""
    if claves:
        for clave in str(fila.get("Claves ProdServ") or "").split(","):
            clave = clave.strip()
            if clave and clave.startswith(claves):
                return True
    desc = fila.get("_Descripcion_Norm", "")
    return any(re.search(rf"(?<![a-z0-9]){re.escape(p)}(?![a-z0-9])", desc)
               for p in palabras) if desc else False


def _motivo_no_deducible(fila: pd.Series, palabras: List[str], frases: List[str],
                         claves: set) -> str:
    """
    Primero la clave del catalogo del SAT -- solo existe si la fuente es XML y es
    mucho mas confiable que el texto. Despues, la descripcion.
    """
    if claves:
        for clave in str(fila.get("Claves ProdServ") or "").split(","):
            clave = clave.strip()
            if clave and clave in claves:
                return f"el concepto usa la clave SAT {clave}, marcada como no deducible"
    palabra = _buscar_lista_negra(fila.get("_Descripcion_Norm", ""), palabras, frases)
    return f"se detecto '{palabra}' en la descripcion" if palabra else ""


def _buscar_lista_negra(desc_norm: str, palabras: List[str], frases: List[str]) -> str:
    """Coincidencia por palabra completa (evita que 'cine' pegue con 'cocina')."""
    if not desc_norm:
        return ""
    for frase in frases:
        if frase and frase in desc_norm:
            return frase
    for palabra in palabras:
        if not palabra:
            continue
        if " " in palabra:
            if palabra in desc_norm:
                return palabra
        elif re.search(rf"(?<![a-z0-9]){re.escape(palabra)}(?![a-z0-9])", desc_norm):
            return palabra
    return ""


# =============================================================================
# 7. TOTALES: UN BLOQUE POR ARCHIVO + GRAN TOTAL
# =============================================================================

def _suma(sub: pd.DataFrame, col: str) -> float:
    if sub is None or sub.empty or col not in sub.columns:
        return 0.0
    return round(float(pd.to_numeric(sub[col], errors="coerce").fillna(0).sum()), 2)


def sumar_por_moneda(df: pd.DataFrame,
                     columnas: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """
    Totaliza cada columna de importe. Tras la conversion todo esta en MXN, asi que
    normalmente devuelve una sola fila; se conserva el agrupado por si se apaga
    la conversion en config_reglas.json.
    """
    columnas = columnas or (COLUMNAS_IMPORTE + ["Importe Computado"])
    if df is None or df.empty:
        return []
    cols = [c for c in columnas if c in df.columns]
    if "Moneda" in df.columns:
        monedas = df["Moneda"].fillna("").replace("", "MXN")
    else:
        monedas = pd.Series(["MXN"] * len(df), index=df.index)

    salida: List[Dict[str, Any]] = []
    for moneda, grupo in df.groupby(monedas, sort=True):
        fila: Dict[str, Any] = {"Moneda": str(moneda) or "MXN",
                                "Comprobantes": int(len(grupo))}
        for c in cols:
            fila[c] = _suma(grupo, c)
        salida.append(fila)
    return salida


def _desglose_formas_pago(sub: pd.DataFrame) -> List[Dict[str, Any]]:
    """Para el archivo de Pagos: cuanto se pago con cada forma (efectivo, tarjeta...)."""
    if sub is None or sub.empty:
        return []
    salida = []
    for clave, grupo in sub.groupby(sub["Forma Pago"].fillna(""), sort=True):
        clave = str(clave)
        fuera = grupo[~grupo["_Suma"]]
        salida.append({
            "clave": clave or "--",
            "descripcion": FORMAS_PAGO.get(clave, "No especificada"),
            "conteo": int(len(grupo)),
            "monto_total": _suma(grupo, "Importe Base"),
            "monto": _suma(grupo, "Importe Computado"),
            "rechazado": _suma(fuera, "Importe Base"),
            "conteo_rechazado": int(len(fuera)),
        })
    return sorted(salida, key=lambda d: d["monto"], reverse=True)


def calcular_bloque(sub: pd.DataFrame, origen: str) -> Dict[str, Any]:
    """Totales de un archivo (Emitidas, Recibidas, Pagos, Nominas o Egresos)."""
    suma = sub[sub["_Suma"]] if "_Suma" in sub.columns else sub.iloc[0:0]
    nc = sub[sub["Tipo Comprobante"] == "E"]
    ppd = sub[sub["Regla Aplicada"] == "Regla 2"]
    ppd = ppd[~ppd["_Suma"]]
    rech = sub[~sub["_Aceptado"]]

    bloque: Dict[str, Any] = {
        "origen": origen,
        "etiqueta": ETIQUETAS_ORIGEN.get(origen, origen.title()),
        "archivos": sorted({str(a) for a in sub.get("Archivo Origen", pd.Series(dtype=str))
                            .dropna().unique()}),
        "conteo": int(len(sub)),
        "conteo_suma": int(len(suma)),
        "total": _suma(suma, "Importe Computado"),
        "subtotal": _suma(suma, "Subtotal"),
        "descuento": _suma(suma, "Descuento"),
        "iva": _suma(suma, "IVA"),
        "iva_acreditable": _suma(sub, "IVA Acreditable"),
        "ieps": _suma(suma, "IEPS"),
        "iva_retenido": _suma(suma, "IVA Retenido"),
        "isr_retenido": _suma(suma, "ISR Retenido"),
        "retenciones": _suma(suma, "Retenciones"),
        "percepciones": _suma(suma, "Percepciones"),
        "deducciones": _suma(suma, "Deducciones"),
        "otros_pagos": _suma(suma, "Otros Pagos"),
        "neto_pagado": _suma(suma, "Total"),
        "base_16": _suma(suma, "Base 16"),
        "base_8": _suma(suma, "Base 8"),
        "base_0": _suma(suma, "Base 0"),
        "base_exento": _suma(suma, "Base Exento"),
        "base_sin_clasificar": _suma(suma, "Base Sin Clasificar"),
        "iva_8": _suma(suma, "IVA Tasa 8"),
        "deducciones_personales": {
            "conteo": int((sub["Regla Aplicada"] == "Deduccion personal").sum()),
            "monto": _suma(sub[sub["Regla Aplicada"] == "Deduccion personal"],
                           "Importe Base")},
        "combustible_rechazado": {
            "conteo": int((sub["Regla Aplicada"] == "Combustible").sum()),
            "monto": _suma(sub[sub["Regla Aplicada"] == "Combustible"], "Importe Base")},
        "inversiones": {
            "conteo": int((sub["Regla Aplicada"] == "Inversion").sum()),
            "monto": _suma(sub[sub["Regla Aplicada"] == "Inversion"], "Importe Base"),
            "iva": _suma(sub[sub["Regla Aplicada"] == "Inversion"], "IVA Acreditable")},
        "sustituidas": {
            "conteo": int((sub["Regla Aplicada"] == "Sustitucion").sum()),
            "monto": _suma(sub[sub["Regla Aplicada"] == "Sustitucion"], "Importe Base")},
        "restaurantes": {
            "conteo": int((sub["Regla Aplicada"] == "Restaurante").sum()),
            "monto": _suma(sub[(sub["Regla Aplicada"] == "Restaurante") & sub["_Suma"]],
                           "Importe Base"),
            "deducible": _suma(sub[(sub["Regla Aplicada"] == "Restaurante") & sub["_Suma"]],
                               "Importe Computado")},
        "alertas": int((sub["Alertas"].fillna("").astype(str).str.strip() != "").sum())
        if "Alertas" in sub.columns else 0,
        "notas_credito": {"conteo": int(len(nc)), "monto": _suma(nc, "Importe Base")},
        "ppd_excluido": {"conteo": int(len(ppd)), "monto": _suma(ppd, "Importe Base")},
        "rechazado": {"conteo": int(len(rech)), "monto": _suma(rech, "Importe Base")},
        "incompletos": int(sub.get("_Importes_Incompletos",
                                   pd.Series(False, index=sub.index)).sum()),
    }
    if origen == "PAGOS":
        bloque["formas_pago"] = _desglose_formas_pago(sub)
        efectivo = sub[sub["Forma Pago"] == "01"]
        bloque["efectivo"] = {
            "conteo": int(len(efectivo)),
            "monto": _suma(efectivo, "Importe Base"),
            "deducible": _suma(efectivo, "Importe Computado"),
            "excede_tope_conteo": int((~efectivo["_Aceptado"]).sum()),
            "excede_tope_monto": _suma(efectivo[~efectivo["_Aceptado"]], "Importe Base"),
        }
    return bloque


def calcular_totales(df: pd.DataFrame) -> Dict[str, Any]:
    """
    Devuelve un bloque de totales por cada archivo cargado, mas el gran total.

    Deducible = Recibidas + Egresos + Nominas + REP de Pagos
    Los ingresos (Emitidas) van aparte: no son una deduccion.
    """
    vacios = ("total_deducible", "total_ingresos", "iva_acreditable", "iva_trasladado",
              "total_retenciones", "total_rechazado", "total_notas_credito",
              "total_ppd_excluido", "total_subtotal", "total_ieps",
              "total_iva_retenido", "total_isr_retenido", "total_descuento")
    if df.empty or "_Suma" not in df.columns:
        vacio: Dict[str, Any] = {k: 0.0 for k in vacios}
        vacio.update({"conteo_total": 0, "conteo_aceptados": 0, "conteo_rechazados": 0,
                      "conteo_revisar": 0, "conteo_por_regla": {}, "periodo": "",
                      "total_inversiones": 0.0, "conteo_inversiones": 0, "iva_inversiones": 0.0,
                      "conteo_sustituidas": 0, "total_sustituidas": 0.0,
                      "conteo_restaurantes": 0, "restaurantes_base": 0.0,
                      "restaurantes_deducible": 0.0, "conteo_alertas": 0,
                      "monedas": [], "multimoneda": False, "bloques": [],
                      "tipos_cambio": {}, "desglose_aceptados": [],
                      "desglose_rechazados": [], "desglose_revisar": [],
                      "filas_forzadas_por_color": 0, "conflictos_color": 0,
                      "iva_calculado": 0, "importes_incompletos": 0,
                      "total_pue": 0.0, "total_nomina": 0.0, "total_pagos": 0.0})
        return vacio

    ok = df[df["_Aceptado"]]
    no = df[~df["_Aceptado"]]
    suman = df[df["_Suma"]]

    origenes = [o for o in ORDEN_ORIGENES
                if o in set(df.get("Origen", pd.Series(dtype=str)).dropna())]
    bloques = [calcular_bloque(df[df["Origen"] == o], o) for o in origenes]
    por_origen = {b["origen"]: b for b in bloques}

    gasto = ["RECIBIDAS", "EGRESOS", "NOMINAS", "PAGOS"]
    deducible = sum(por_origen[o]["total"] for o in gasto if o in por_origen)
    ingresos = por_origen.get("EMITIDAS", {}).get("total", 0.0)
    otros = sum(b["total"] for b in bloques if b["origen"] not in gasto + ["EMITIDAS"])

    iva_acreditable = sum(por_origen[o]["iva_acreditable"] for o in ("RECIBIDAS", "EGRESOS")
                          if o in por_origen)

    # --- Desglose por tasa de lo que se compro y se pago ------------------
    # Es el corte que pide la declaracion: tasa 16, tasa 0, exentos, y la
    # nomina aparte (su gasto es el total de percepciones).
    gasto_iva = [o for o in ("RECIBIDAS", "EGRESOS", "PAGOS") if o in por_origen]
    def _tasas(clave: str) -> float:
        return round(sum(por_origen[o].get(clave, 0.0) for o in gasto_iva), 2)

    nomina = por_origen.get("NOMINAS", {})
    desglose_tasas = {
        "base_16": _tasas("base_16"),
        "iva_16": _tasas("iva"),
        "base_8": _tasas("base_8"),
        "iva_8": _tasas("iva_8"),
        "base_0": _tasas("base_0"),
        "base_exento": _tasas("base_exento"),
        "base_sin_clasificar": _tasas("base_sin_clasificar"),
        "nomina_percepciones": round(nomina.get("percepciones", 0.0), 2),
        "nomina_deducciones": round(nomina.get("deducciones", 0.0), 2),
        "nomina_neto": round(nomina.get("neto_pagado", 0.0), 2),
        "origenes": [ETIQUETAS_ORIGEN.get(o, o) for o in gasto_iva],
    }
    desglose_tasas["base_total"] = round(
        desglose_tasas["base_16"] + desglose_tasas["base_8"]
        + desglose_tasas["base_0"] + desglose_tasas["base_exento"]
        + desglose_tasas["base_sin_clasificar"], 2)
    iva_trasladado = por_origen.get("EMITIDAS", {}).get("iva", 0.0)

    fechas = df["Fecha Emision"].dropna()
    periodo = f"{fechas.min():%d/%m/%Y} al {fechas.max():%d/%m/%Y}" if not fechas.empty else ""
    conteo_regla = no["Regla Aplicada"].value_counts().to_dict() if not no.empty else {}

    revisar = df[df["_Conflicto_Color"] == True] if "_Conflicto_Color" in df.columns \
        else df.iloc[0:0]
    monedas = sorted(set(df["Moneda Original"].dropna().astype(str))) \
        if "Moneda Original" in df.columns else ["MXN"]

    return {
        # --- Gran total -----------------------------------------------
        "total_deducible": round(deducible + otros, 2),
        "total_ingresos": round(ingresos, 2),
        "iva_acreditable": round(iva_acreditable, 2),
        "iva_trasladado": round(iva_trasladado, 2),
        "total_subtotal": _suma(suman, "Subtotal"),
        "total_descuento": _suma(suman, "Descuento"),
        "total_ieps": _suma(suman, "IEPS"),
        "total_iva_retenido": _suma(suman, "IVA Retenido"),
        "total_isr_retenido": _suma(suman, "ISR Retenido"),
        "total_retenciones": _suma(suman, "Retenciones"),
        "total_rechazado": _suma(no, "Importe Base"),
        "subtotal_deducible": round(sum(por_origen[o]["subtotal"] for o in gasto
                                        if o in por_origen), 2),
        "subtotal_ingresos": round(por_origen.get("EMITIDAS", {}).get("subtotal", 0.0), 2),
        "total_notas_credito": round(sum(b["notas_credito"]["monto"] for b in bloques), 2),
        "conteo_notas_credito": int(sum(b["notas_credito"]["conteo"] for b in bloques)),
        "total_ppd_excluido": round(sum(b["ppd_excluido"]["monto"] for b in bloques), 2),
        "conteo_ppd_excluido": int(sum(b["ppd_excluido"]["conteo"] for b in bloques)),
        "total_inversiones": round(sum(b["inversiones"]["monto"] for b in bloques), 2),
        "conteo_inversiones": int(sum(b["inversiones"]["conteo"] for b in bloques)),
        "iva_inversiones": round(sum(b["inversiones"]["iva"] for b in bloques), 2),
        "conteo_sustituidas": int(sum(b["sustituidas"]["conteo"] for b in bloques)),
        "total_sustituidas": round(sum(b["sustituidas"]["monto"] for b in bloques), 2),
        "conteo_restaurantes": int(sum(b["restaurantes"]["conteo"] for b in bloques)),
        "restaurantes_base": round(sum(b["restaurantes"]["monto"] for b in bloques), 2),
        "restaurantes_deducible": round(sum(b["restaurantes"]["deducible"] for b in bloques), 2),
        "conteo_alertas": int(sum(b["alertas"] for b in bloques)),
        # --- Compatibilidad con la vista anterior ----------------------
        "total_pue": _suma(suman[suman["Tipo Comprobante"] == "I"], "Importe Computado"),
        "total_nomina": _suma(suman[suman["Tipo Comprobante"] == "N"], "Importe Computado"),
        "total_pagos": _suma(suman[suman["Tipo Comprobante"] == "P"], "Importe Computado"),
        "total_iva": _suma(suman, "IVA"),
        "total_iva_rechazado": _suma(no, "IVA"),
        "total_neto_nomina": round(por_origen.get("NOMINAS", {}).get("neto_pagado", 0.0), 2),
        "total_percepciones": round(por_origen.get("NOMINAS", {}).get("percepciones", 0.0), 2),
        "total_deducciones": round(por_origen.get("NOMINAS", {}).get("deducciones", 0.0), 2),
        # --- Desglose por tasa de IVA ---------------------------------
        "desglose_tasas": desglose_tasas,
        # --- Bloques por archivo --------------------------------------
        "bloques": bloques,
        # --- Conteos y contexto ---------------------------------------
        "conteo_total": int(len(df)),
        "conteo_aceptados": int(len(ok)),
        "conteo_rechazados": int(len(no)),
        "conteo_suma": int(len(suman)),
        "conteo_revisar": int(len(revisar)),
        "conteo_por_regla": {str(k): int(v) for k, v in conteo_regla.items()},
        "monedas": monedas,
        "multimoneda": len(monedas) > 1,
        "desglose_aceptados": sumar_por_moneda(ok),
        "desglose_rechazados": sumar_por_moneda(no),
        "desglose_revisar": sumar_por_moneda(revisar),
        "iva_calculado": int(df.get("_IVA_Calculado", pd.Series(dtype=bool)).sum()),
        "importes_incompletos": int(df.get("_Importes_Incompletos",
                                           pd.Series(dtype=bool)).sum()),
        "filas_forzadas_por_color": int(df.get("_Forzado_Por_Color",
                                               pd.Series(dtype=bool)).sum()),
        "conflictos_color": int(df.get("_Conflicto_Color", pd.Series(dtype=bool)).sum()),
        "periodo": periodo,
    }


# =============================================================================
# 8. EXPORTACION DEL EXCEL DEPURADO (UNA HOJA POR ARCHIVO + RESUMEN)
# =============================================================================

# Orden pensado para revisar de izquierda a derecha: quien -> que -> cuanto -> resultado
COLUMNAS_SALIDA = [
    "Origen", "Archivo Origen", "UUID", "Fecha Emision",
    "RFC Emisor", "Nombre Emisor", "RFC Receptor", "Nombre Receptor",
    "Tipo Comprobante", "Tipo Comprobante Desc", "Uso CFDI", "Uso CFDI Desc",
    "Forma Pago", "Forma Pago Desc", "Metodo Pago", "Metodo Pago Desc",
    "Descripcion", "Claves ProdServ", "UUID Relacionados",
    "Moneda Original", "Tipo de Cambio", "Total Original",
    "Subtotal", "Descuento", "IVA", "IEPS",
    "IVA Retenido", "ISR Retenido", "Retenciones",
    "Percepciones", "Deducciones", "Otros Pagos",
    "Total", "Monto Pagado", "Importe Computado", "IVA Acreditable", "Suma",
    "Clasificacion", "Regla Aplicada", "Motivo de Rechazo", "Alertas",
    "Estatus SAT Consulta", "Cancelacion SAT",
]

# Columnas que se ocultan en una hoja cuando valen 0 en todos sus renglones
OCULTABLES = ["Claves ProdServ", "UUID Relacionados",
              "Descuento", "IVA", "IEPS", "IVA Retenido", "ISR Retenido", "Retenciones",
              "Percepciones", "Deducciones", "Otros Pagos", "Monto Pagado",
              "Moneda Original", "Tipo de Cambio", "Total Original"]


def _vista(df: pd.DataFrame, podar: bool = True) -> pd.DataFrame:
    """Subconjunto ordenado de columnas; quita las de importe que van en ceros."""
    if df.empty:
        return pd.DataFrame(columns=[c for c in COLUMNAS_SALIDA])
    datos = df.copy()
    datos["Suma"] = datos["_Suma"].map({True: "SI", False: "NO"}) \
        if "_Suma" in datos.columns else ""
    cols = [c for c in COLUMNAS_SALIDA if c in datos.columns]

    if podar:
        # Sin divisa extranjera no tiene caso arrastrar las columnas de conversion
        sin_divisa = set(datos.get("Moneda Original", pd.Series(dtype=str))
                         .dropna().astype(str)) <= {"MXN", ""}
        for col in OCULTABLES:
            if col not in cols:
                continue
            if col in ("Moneda Original", "Tipo de Cambio", "Total Original"):
                if sin_divisa:
                    cols.remove(col)
                continue
            if col in ("Claves ProdServ", "UUID Relacionados"):
                # Solo existen cuando la fuente fue XML
                if not datos[col].astype(str).str.strip().any():
                    cols.remove(col)
                continue
            serie = datos[col]
            if pd.api.types.is_numeric_dtype(serie):
                if float(pd.to_numeric(serie, errors="coerce").fillna(0).abs().sum()) == 0:
                    cols.remove(col)
        # En una hoja de un solo archivo, 'Origen' es la misma palabra en cada renglon
        if "Origen" in cols and datos["Origen"].nunique() <= 1:
            cols.remove("Origen")

    salida = datos[cols].copy()
    if "Fecha Emision" in salida.columns:
        salida["Fecha Emision"] = pd.to_datetime(salida["Fecha Emision"], errors="coerce")
    if "Fecha Emision" in salida.columns:
        salida = salida.sort_values(["Fecha Emision", "UUID"], na_position="last")
    return salida.reset_index(drop=True)


def _filas_resumen(totales: Dict[str, Any]) -> List[Tuple[Any, Any]]:
    f: List[Tuple[Any, Any]] = [
        ("REPORTE DE AUDITORIA CFDI 4.0", ""),
        ("Periodo analizado", totales.get("periodo", "")),
        ("Generado", datetime.now().strftime("%d/%m/%Y %H:%M")),
        ("Comprobantes procesados", totales.get("conteo_total", 0)),
        ("", ""),
        ("=== GRAN TOTAL ===", ""),
        ("Ingresos facturados (Emitidas)", totales.get("total_ingresos", 0)),
        ("TOTAL DEDUCIBLE (gastos + nomina + REP)", totales.get("total_deducible", 0)),
        ("", ""),
        ("IVA trasladado (de lo emitido)", totales.get("iva_trasladado", 0)),
        ("IVA acreditable (de lo recibido)", totales.get("iva_acreditable", 0)),
        ("IEPS", totales.get("total_ieps", 0)),
        ("IVA retenido", totales.get("total_iva_retenido", 0)),
        ("ISR retenido", totales.get("total_isr_retenido", 0)),
        ("Total retenciones", totales.get("total_retenciones", 0)),
        ("Descuentos", totales.get("total_descuento", 0)),
        ("Base deducible sin IVA (gastos y nomina)", totales.get("subtotal_deducible", 0)),
        ("Base facturada sin IVA (emitidas)", totales.get("subtotal_ingresos", 0)),
    ]

    t = totales.get("desglose_tasas") or {}
    if t:
        f += [("", ""),
              (f"=== DESGLOSE POR TASA ({' + '.join(t.get('origenes', []))}) ===", "")]
        f.append(("Base tasa 16%", t.get("base_16", 0)))
        f.append(("   IVA trasladado 16%", t.get("iva_16", 0)))
        if t.get("base_8"):
            f.append(("Base tasa 8%", t.get("base_8", 0)))
            f.append(("   IVA trasladado 8%", t.get("iva_8", 0)))
        f.append(("Base tasa 0%", t.get("base_0", 0)))
        f.append(("Base exenta", t.get("base_exento", 0)))
        if t.get("base_sin_clasificar"):
            f.append(("Base sin clasificar (revisar)", t.get("base_sin_clasificar", 0)))
        f.append(("= Base total sin IVA", t.get("base_total", 0)))
        f.append(("", ""))
        f.append(("Nomina - total de percepciones", t.get("nomina_percepciones", 0)))
        f.append(("   Nomina - deducciones", t.get("nomina_deducciones", 0)))
        f.append(("   Nomina - neto depositado", t.get("nomina_neto", 0)))

    f += [
        ("", ""),
        ("--- Excluido de la sumatoria ---", ""),
        (f"Notas de credito ({totales.get('conteo_notas_credito', 0)} CFDI)",
         totales.get("total_notas_credito", 0)),
        (f"PPD sin REP ({totales.get('conteo_ppd_excluido', 0)} CFDI)",
         totales.get("total_ppd_excluido", 0)),
        (f"Rechazados por reglas ({totales.get('conteo_rechazados', 0)} CFDI)",
         totales.get("total_rechazado", 0)),
        (f"Inversiones, van a activo fijo ({totales.get('conteo_inversiones', 0)} CFDI)",
         totales.get("total_inversiones", 0)),
        (f"Sustituidas por otra factura ({totales.get('conteo_sustituidas', 0)} CFDI)",
         totales.get("total_sustituidas", 0)),
    ]
    if totales.get("conteo_restaurantes"):
        f += [("", ""), ("--- Restaurantes (deduccion parcial) ---", ""),
              (f"Consumos ({totales['conteo_restaurantes']} CFDI)", totales.get("restaurantes_base", 0)),
              ("   Parte deducible", totales.get("restaurantes_deducible", 0))]
    tp = totales.get("deducciones_personales_tope") or {}
    if tp:
        f += [("", ""), ("--- Deducciones personales (declaracion anual) ---", ""),
              (f"Monto detectado ({tp['conteo']} CFDI)", tp["monto"]),
              ("   Tope: 5 UMA anuales", tp["tope_5_uma"])]
        if tp.get("tope_15_ingresos") is not None:
            f.append(("   Tope: 15 % de los ingresos", tp["tope_15_ingresos"]))
        f.append(("   Excede el tope global", tp["excede"]))
    if totales.get("iva_inversiones"):
        f.append(("IVA acreditable de inversiones (incluido arriba)", totales["iva_inversiones"]))
    es = totales.get("estatus_sat") or {}
    if es:
        f += [("", ""), ("--- Estatus consultado en el SAT ---", ""),
              ("CFDI consultados", es.get("total", 0)),
              ("   Cancelados (no suman)", es.get("cancelados", 0)),
              ("   No encontrados (revisar)", es.get("no_encontrados", 0)),
              ("   Sin respuesta del SAT", es.get("errores", 0))]
    if totales.get("conteo_alertas"):
        f.append((f"CFDI con ALERTAS para revisar ({totales['conteo_alertas']})", totales["conteo_alertas"]))

    tc = totales.get("tipos_cambio") or {}
    if tc:
        f += [("", ""), ("=== TIPO DE CAMBIO APLICADO ===", "")]
        for moneda, info in tc.items():
            if moneda == "MXN":
                continue
            f.append((f"{moneda} -> MXN", info.get("tasa")))
            f.append((f"   fuente", info.get("fuente", "")))

    for bloque in totales.get("bloques", []):
        f += [("", ""), (f"=== {bloque['etiqueta'].upper()} ===",
                         ", ".join(bloque.get("archivos", [])))]
        f.append((f"Comprobantes ({bloque['conteo_suma']} suman de {bloque['conteo']})",
                  bloque["conteo"]))
        f.append(("Total que suma", bloque["total"]))
        for etiqueta, clave in (("Subtotal", "subtotal"), ("Descuento", "descuento"),
                                ("IVA", "iva"), ("IEPS", "ieps"),
                                ("IVA retenido", "iva_retenido"),
                                ("ISR retenido", "isr_retenido"),
                                ("Total retenciones", "retenciones"),
                                ("Percepciones", "percepciones"),
                                ("Deducciones", "deducciones"),
                                ("Otros pagos", "otros_pagos")):
            if bloque.get(clave):
                f.append((f"   {etiqueta}", bloque[clave]))
        if bloque["notas_credito"]["conteo"]:
            f.append((f"   (excluido) Notas de credito x{bloque['notas_credito']['conteo']}",
                      bloque["notas_credito"]["monto"]))
        if bloque["ppd_excluido"]["conteo"]:
            f.append((f"   (excluido) PPD sin REP x{bloque['ppd_excluido']['conteo']}",
                      bloque["ppd_excluido"]["monto"]))
        if bloque["rechazado"]["conteo"]:
            f.append((f"   (excluido) Rechazados x{bloque['rechazado']['conteo']}",
                      bloque["rechazado"]["monto"]))
        for forma in bloque.get("formas_pago", []):
            etiqueta = (f"   Pago {forma['clave']} {forma['descripcion']} "
                        f"x{forma['conteo']}")
            if forma.get("rechazado"):
                etiqueta += f" (fuera {forma['rechazado']:,.2f})"
            f.append((etiqueta, forma["monto"]))
    return f


def exportar_excel(df: pd.DataFrame, totales: Dict[str, Any], ruta_salida: str) -> str:
    """
    Excel depurado con: Resumen General, una hoja por archivo cargado,
    Notas de Credito, No Sumados y el Detalle Completo.
    """
    resumen = pd.DataFrame(_filas_resumen(totales), columns=["Concepto", "Importe"])

    hojas: List[Tuple[str, pd.DataFrame, List[Dict[str, Any]]]] = []
    for bloque in totales.get("bloques", []):
        sub = df[df["Origen"] == bloque["origen"]]
        if sub.empty:
            continue
        hojas.append((bloque["etiqueta"][:31], _vista(sub),
                      sumar_por_moneda(sub[sub["_Suma"]])))

    nc = df[df["Tipo Comprobante"] == "E"]
    if not nc.empty:
        hojas.append(("Notas de Credito", _vista(nc), sumar_por_moneda(nc)))

    fuera = df[~df["_Suma"]] if "_Suma" in df.columns else df.iloc[0:0]
    if not fuera.empty:
        hojas.append(("No Sumados", _vista(fuera), sumar_por_moneda(fuera)))

    hojas.append(("Detalle Completo", _vista(df, podar=False),
                  sumar_por_moneda(df[df["_Suma"]])))

    with pd.ExcelWriter(ruta_salida, engine="openpyxl") as writer:
        resumen.to_excel(writer, sheet_name="Resumen General", index=False)
        for nombre, datos, _ in hojas:
            datos.to_excel(writer, sheet_name=nombre, index=False)

    if OPENPYXL_OK:
        _dar_formato(ruta_salida, {n: d for n, _, d in hojas})
    return ruta_salida


def _agregar_filas_totales(hoja, desglose: List[Dict[str, Any]]) -> List[int]:
    """Agrega al pie de la hoja una fila TOTAL por moneda. Devuelve sus indices."""
    if not desglose or hoja.max_row < 1:
        return []
    encabezados = {str(hoja.cell(row=1, column=c).value or ""): c
                   for c in range(1, hoja.max_column + 1)}
    filas_totales = []
    for fila in desglose:
        r = hoja.max_row + 1
        hoja.cell(row=r, column=1,
                  value=f"TOTAL {fila['Moneda']} ({fila['Comprobantes']} CFDI)")
        for nombre, valor in fila.items():
            if nombre in ("Moneda", "Comprobantes"):
                continue
            col = encabezados.get(nombre)
            if col:
                hoja.cell(row=r, column=col, value=valor)
        filas_totales.append(r)
    return filas_totales


COLUMNAS_DINERO = {"Subtotal", "Descuento", "IVA", "IEPS", "IVA Retenido", "ISR Retenido",
                   "Retenciones", "Percepciones", "Deducciones", "Otros Pagos",
                   "Total", "Monto Pagado", "Importe Computado", "Total Original",
                   "Importe"}


def _dar_formato(ruta: str, desgloses: Optional[Dict[str, List[Dict[str, Any]]]] = None) -> None:
    wb = load_workbook(ruta)
    encabezado_fill = PatternFill("solid", fgColor="FF1F3864")
    encabezado_font = Font(color="FFFFFFFF", bold=True, size=11)
    borde = Border(*[Side(style="thin", color="FFD9D9D9")] * 4)
    desgloses = desgloses or {}

    for hoja in wb.worksheets:
        filas_datos = hoja.max_row
        filas_totales = _agregar_filas_totales(hoja, desgloses.get(hoja.title, []))

        for celda in hoja[1]:
            celda.fill = encabezado_fill
            celda.font = encabezado_font
            celda.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        hoja.freeze_panes = "C2" if hoja.max_column > 4 else "A2"
        if filas_datos > 1 and hoja.max_column > 0:
            hoja.auto_filter.ref = f"A1:{get_column_letter(hoja.max_column)}{filas_datos}"

        for col in range(1, hoja.max_column + 1):
            letra = get_column_letter(col)
            titulo = str(hoja.cell(row=1, column=col).value or "")
            ancho = max(12, min(48, len(titulo) + 6))
            largos = [len(str(hoja.cell(row=r, column=col).value or ""))
                      for r in range(2, min(hoja.max_row, 200) + 1)]
            if largos:
                ancho = max(ancho, min(48, max(largos) + 3))
            hoja.column_dimensions[letra].width = ancho
            if titulo in COLUMNAS_DINERO:
                for r in range(2, hoja.max_row + 1):
                    c = hoja.cell(row=r, column=col)
                    if isinstance(c.value, (int, float)):
                        c.number_format = '$#,##0.00'
            elif titulo == "Tipo de Cambio":
                for r in range(2, hoja.max_row + 1):
                    hoja.cell(row=r, column=col).number_format = '0.0000'
            elif titulo == "Fecha Emision":
                for r in range(2, hoja.max_row + 1):
                    hoja.cell(row=r, column=col).number_format = 'DD/MM/YYYY'
            for r in range(2, hoja.max_row + 1):
                hoja.cell(row=r, column=col).border = borde

        # Los renglones que NO suman se pintan en gris para distinguirlos de un vistazo
        cols = {str(hoja.cell(row=1, column=c).value or ""): c
                for c in range(1, hoja.max_column + 1)}
        if "Suma" in cols:
            gris = Font(color="FF8A8A8A", italic=True)
            for r in range(2, filas_datos + 1):
                if str(hoja.cell(row=r, column=cols["Suma"]).value or "") == "NO":
                    for c in range(1, hoja.max_column + 1):
                        hoja.cell(row=r, column=c).font = gris

        for r in filas_totales:
            for c in range(1, hoja.max_column + 1):
                celda = hoja.cell(row=r, column=c)
                celda.font = Font(bold=True, size=11, color="FF1F3864")
                celda.fill = PatternFill("solid", fgColor="FFDDEBF7")

    hoja = wb["Resumen General"]
    hoja.column_dimensions["A"].width = 52
    hoja.column_dimensions["B"].width = 24
    for r in range(2, hoja.max_row + 1):
        etiqueta = str(hoja.cell(row=r, column=1).value or "")
        if etiqueta.startswith("==="):
            for c in (1, 2):
                hoja.cell(row=r, column=c).font = Font(bold=True, size=12, color="FFFFFFFF")
                hoja.cell(row=r, column=c).fill = PatternFill("solid", fgColor="FF2F5597")
        elif etiqueta.startswith("TOTAL DEDUCIBLE") or etiqueta.startswith("Ingresos facturados"):
            for c in (1, 2):
                hoja.cell(row=r, column=c).font = Font(bold=True, size=13, color="FF006100")
                hoja.cell(row=r, column=c).fill = PatternFill("solid", fgColor="FFC6EFCE")
        elif etiqueta.startswith("---"):
            for c in (1, 2):
                hoja.cell(row=r, column=c).font = Font(bold=True, color="FF9C0006")
    wb.save(ruta)


# =============================================================================
# 9. CONVERSION DE DIVISAS Y ORQUESTADOR
# =============================================================================

def convertir_a_mxn(df: pd.DataFrame, config: Dict[str, Any]
                    ) -> Tuple[pd.DataFrame, Dict[str, Any], List[str]]:
    """
    Deja TODOS los importes en pesos. Conserva la divisa y el monto originales
    mas el tipo de cambio usado, para que la conversion sea auditable.
    """
    avisos: List[str] = []
    info: Dict[str, Any] = {}
    if df.empty:
        return df, info, avisos

    df = df.copy()
    df["Moneda Original"] = df["Moneda"]
    df["Total Original"] = df["Total"]
    df["Tipo de Cambio"] = 1.0

    if not bool(config.get("convertir_a_mxn", True)):
        avisos.append("Conversion a MXN desactivada en config_reglas.json.")
        return df, info, avisos

    # XXX es la clave del SAT para "sin moneda"; la usan los complementos de pago.
    extranjeras = sorted(set(df["Moneda"].dropna().astype(str)) - {"MXN", "", "XXX"})
    info["MXN"] = {"tasa": 1.0, "fuente": "moneda base", "fecha": "", "confiable": True}
    if not extranjeras:
        return df, info, avisos

    # El XML del CFDI trae el tipo de cambio que el emisor declaro ante el SAT.
    # Ese es el bueno: manda sobre cualquier consulta de mercado.
    if "Tipo Cambio CFDI" in df.columns:
        propio = (df["Moneda"].isin(extranjeras)
                  & (pd.to_numeric(df["Tipo Cambio CFDI"], errors="coerce").fillna(0) > 0))
        if propio.any():
            df.loc[propio, "Tipo de Cambio"] = pd.to_numeric(
                df.loc[propio, "Tipo Cambio CFDI"], errors="coerce")
            info["CFDI"] = {"tasa": None, "moneda": "declarado en el XML",
                            "fuente": f"TipoCambio del propio CFDI ({int(propio.sum())} comprobantes)",
                            "fecha": "", "confiable": True}
            avisos.append(f"{int(propio.sum())} CFDI traen su propio tipo de cambio "
                          f"declarado: se usa ese, no el de mercado.")

    modo = str(config.get("modo_tipo_cambio", "actual")).lower()
    combos: List[Tuple[str, Any]] = []
    if modo == "fecha":
        pares = df.loc[df["Moneda"].isin(extranjeras), ["Moneda", "Fecha Emision"]].dropna()
        combos = sorted({(m, f.date()) for m, f in pares.itertuples(index=False)})
        if len(combos) > 40:
            avisos.append(f"{len(combos)} combinaciones moneda/fecha: se usa el tipo de "
                          f"cambio actual para no saturar el servicio.")
            combos, modo = [], "actual"

    if modo == "fecha" and combos:
        for moneda, dia in combos:
            datos = tc_obtener_tasa(moneda, config, dia)
            clave = f"{moneda}@{dia:%Y-%m-%d}"
            info[clave] = dict(datos, moneda=moneda, fecha_cfdi=str(dia))
            if not datos.get("tasa"):
                avisos.append(f"Sin tipo de cambio para {moneda} del {dia:%d/%m/%Y}.")
                continue
            sel = ((df["Moneda"] == moneda) & (df["Fecha Emision"].dt.date == dia)
                   & (df["Tipo de Cambio"] == 1.0))
            df.loc[sel, "Tipo de Cambio"] = float(datos["tasa"])
        faltan = (df["Moneda"].isin(extranjeras)) & (df["Fecha Emision"].isna())
        if faltan.any():
            avisos.append(f"{int(faltan.sum())} CFDI en divisa sin fecha legible: "
                          f"se convierten al tipo de cambio actual.")
            for moneda in extranjeras:
                datos = tc_obtener_tasa(moneda, config, None)
                info[moneda] = dict(datos, moneda=moneda)
                if datos.get("tasa"):
                    df.loc[faltan & (df["Moneda"] == moneda), "Tipo de Cambio"] = \
                        float(datos["tasa"])
    else:
        for moneda in extranjeras:
            datos = tc_obtener_tasa(moneda, config, None)
            info[moneda] = dict(datos, moneda=moneda)
            if not datos.get("tasa"):
                avisos.append(f"Sin tipo de cambio para {moneda}: los importes quedan "
                              f"en su divisa original.")
                continue
            if not datos.get("confiable"):
                avisos.append(f"Tipo de cambio de {moneda} obtenido de {datos['fuente']}. "
                              f"Verificalo antes de declarar.")
            # Solo los que no traian su propia tasa declarada en el XML
            sin_tasa = (df["Moneda"] == moneda) & (df["Tipo de Cambio"] == 1.0)
            df.loc[sin_tasa, "Tipo de Cambio"] = float(datos["tasa"])

    convertir = df["Moneda"].isin(extranjeras) & (df["Tipo de Cambio"] != 1.0)
    if convertir.any():
        for col in COLUMNAS_IMPORTE:
            if col in df.columns:
                df.loc[convertir, col] = (df.loc[convertir, col]
                                          * df.loc[convertir, "Tipo de Cambio"]).round(2)
        df.loc[convertir, "Moneda"] = "MXN"
        avisos.append(f"{int(convertir.sum())} CFDI en divisa extranjera convertidos a MXN.")
    return df, info, avisos


ESTATUS_METADATA = {"0": "Cancelado", "1": "Vigente"}


def _aplicar_metadata(registros: List[Dict[str, Any]],
                      tablas: List[Tuple[str, bytes]], diag: Dict[str, Any]) -> int:
    """
    El ZIP de la descarga masiva puede traer el archivo de metadata, que SI dice
    si un CFDI fue cancelado. El XML por si solo no lo sabe.
    """
    if not tablas or not registros:
        return 0
    por_uuid = {str(r.get("UUID", "")).upper(): r for r in registros if r.get("UUID")}
    actualizados = 0

    for nombre, datos in tablas:
        try:
            texto = datos.decode("utf-8-sig", errors="replace")
        except Exception:  # noqa: BLE001
            continue
        lineas = [l for l in texto.splitlines() if l.strip()]
        if len(lineas) < 2:
            continue
        separador = max("~|,\t", key=lambda c: lineas[0].count(c))
        encabezados = [normalizar(h) for h in lineas[0].split(separador)]
        if "uuid" not in encabezados:
            continue
        i_uuid = encabezados.index("uuid")
        i_estatus = encabezados.index("estatus") if "estatus" in encabezados else None
        i_cancel = next((i for i, h in enumerate(encabezados)
                         if "fecha cancelacion" in h), None)

        for linea in lineas[1:]:
            partes = linea.split(separador)
            if len(partes) <= i_uuid:
                continue
            reg = por_uuid.get(partes[i_uuid].strip().upper())
            if reg is None:
                continue
            estatus = ""
            if i_estatus is not None and len(partes) > i_estatus:
                bruto = partes[i_estatus].strip()
                estatus = ESTATUS_METADATA.get(bruto, bruto)
            if not estatus and i_cancel is not None and len(partes) > i_cancel \
                    and partes[i_cancel].strip():
                estatus = "Cancelado"
            if estatus:
                reg["Estatus"] = estatus
                actualizados += 1
        diag.setdefault("avisos", []).append(
            f"Metadata «{nombre}»: se confirmo el estatus SAT de {actualizados} CFDI.")
    return actualizados


def leer_cfdis_xml(ruta: str, config: Dict[str, Any]) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Lee un .xml, un .zip de la descarga masiva o una carpeta con XML dentro.
    A diferencia del Excel, aqui cada CFDI sabe por si mismo de que tipo es,
    asi que el Origen se decide renglon por renglon, no por archivo.
    """
    diag: Dict[str, Any] = {
        "archivo": os.path.basename(ruta), "tipo_fuente": "xml", "hoja": None,
        "fila_encabezado": None, "columnas_detectadas": {}, "columnas_ignoradas": [],
        "filas_rojas": 0, "avisos": [],
    }

    registros, tablas = lector_xml.recolectar(ruta, diag)
    ignorados = diag.pop("ignorados", [])
    if ignorados:
        diag["avisos"].append(f"{len(ignorados)} archivo(s) no eran CFDI y se ignoraron.")
    if not registros:
        return pd.DataFrame(), diag

    _aplicar_metadata(registros, tablas, diag)

    for reg in registros:
        reg.pop("_Pagos_Detalle", None)

    # OJO: aqui NO se decide el Origen. Para saber que es emitida y que recibida
    # hace falta el RFC del contribuyente, y ese se deduce mirando TODOS los
    # archivos de la tanda juntos. Lo hace procesar_archivos.
    df = pd.DataFrame(registros)
    df["_Es_Rojo_Fuente"] = False
    df["_Es_Rojo_Relleno"] = False
    df["_Es_Rojo"] = False

    diag["origen"] = "XML"
    diag["origen_etiqueta"] = f"{len(df)} CFDI"
    diag["origen_detectado_por"] = "el comprobante mismo"
    diag["columnas_detectadas"] = {c: c for c in df.columns if not c.startswith("_")}
    diag["avisos"].append(
        "Leido del XML original: tipo de comprobante, impuestos y claves del "
        "catalogo SAT vienen del comprobante, no de una columna de Excel.")
    return df, diag


def _asignar_origen_xml(marcos_xml: List[Tuple[pd.DataFrame, Dict[str, Any]]],
                        config: Dict[str, Any]) -> Tuple[str, bool]:
    """
    Decide, con toda la tanda a la vista, cual RFC es el del contribuyente y
    marca cada CFDI como Emitida o Recibida. Modifica los marcos en su lugar.
    """
    registros: List[Dict[str, Any]] = []
    for df_x, _ in marcos_xml:
        registros.extend(df_x[["RFC Emisor", "RFC Receptor"]].to_dict("records"))

    rfc = str(config.get("rfc_contribuyente", "") or "").strip().upper()
    if rfc:
        como, ambiguo = "config_reglas.json", False
    else:
        rfc, ambiguo = lector_xml.rfc_del_contribuyente(registros)
        como = "el RFC presente en todos los CFDI de la tanda"

    for df_x, diag in marcos_xml:
        df_x["Origen"] = [lector_xml.origen_de(r, rfc)
                          for r in df_x.to_dict("records")]
        conteo = df_x["Origen"].value_counts().to_dict()
        diag["rfc_contribuyente"] = rfc
        diag["origen_etiqueta"] = " · ".join(
            f"{ETIQUETAS_ORIGEN.get(o, o)} {n}" for o, n in conteo.items())
        diag["origen_detectado_por"] = f"{como} ({rfc or 'no identificado'})"
        if ambiguo:
            diag["avisos"].append(
                f"No se pudo confirmar de quien es la contabilidad: «{rfc}» no aparece "
                f"en todos los comprobantes. Emitidas y Recibidas pueden quedar al "
                f"reves. Captura «rfc_contribuyente» en config_reglas.json para "
                f"asegurarlo, o sube la tanda completa del cliente.")
    return rfc, ambiguo


def verificar_estatus_en_sat(df: pd.DataFrame, cfg: Dict[str, Any]
                             ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """
    Consulta el estatus de cada CFDI en el SAT y corrige la columna Estatus.
    Va ANTES de convertir divisas: el SAT compara contra el total original.
    Si el SAT no responde para un CFDI, su estatus queda como estaba (no se inventa).
    """
    base = df[(df["UUID"].astype(str).str.strip() != "") & (df["RFC Emisor"] != "")
              & (df["RFC Receptor"] != "")]
    cfdis = [{"uuid": str(r["UUID"]), "rfc_emisor": r["RFC Emisor"], "rfc_receptor": r["RFC Receptor"],
              "total": float(r["Total"] or 0)} for _, r in base.iterrows()]
    resultados, resumen = estatus_sat.verificar_lote(
        cfdis, hilos=int(cfg.get("estatus_sat_hilos", 4)),
        timeout=int(cfg.get("estatus_sat_timeout", 15)),
        horas_cache=float(cfg.get("estatus_sat_horas_cache", 24)),
        ruta_cache=cfg.get("estatus_sat_cache") or estatus_sat.RUTA_CACHE,
        consultor=estatus_sat.consultar)
    if not resultados:
        return df, resumen

    df = df.copy()
    uuids = df["UUID"].astype(str).str.upper()
    for col, clave in (("Estatus SAT Consulta", "estado"), ("Cancelacion SAT", "estatus_cancelacion"),
                       ("EFOS SAT", "validacion_efos"), ("Es Cancelable", "es_cancelable")):
        df[col] = uuids.map(lambda u, k=clave: resultados.get(u, {}).get(k, ""))
    cancelado = df["Estatus SAT Consulta"] == "Cancelado"
    vigente = df["Estatus SAT Consulta"] == "Vigente"
    # El SAT en linea manda sobre la metadata y sobre el supuesto "Vigente" del XML
    df.loc[cancelado, "Estatus"] = "Cancelado"
    df.loc[vigente, "Estatus"] = "Vigente"
    resumen["no_verificados"] = int((df["UUID"].astype(str).str.strip() != "").sum()
                                    - df["Estatus SAT Consulta"].astype(bool).sum())
    return df, resumen


def _tope_global_personales(df: pd.DataFrame, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Tope global de deducciones personales [Ley: LISR 151, ultimo parrafo]: lo menor entre
    5 UMA anuales y el 15 % de los ingresos. Solo se calcula si hay deducciones personales.
    Excluye del tope (no distinguible en el CFDI): aportaciones de retiro (V) y gastos por
    incapacidad o discapacidad; si los hay, restalos del monto antes de comparar.
    """
    if df.empty or "Regla Aplicada" not in df.columns:
        return {}
    per = df[df["Regla Aplicada"] == "Deduccion personal"]
    if per.empty:
        return {}
    uma = float(cfg.get("uma_diaria", 117.31) or 0)
    tope_uma = round(5 * uma * 365, 2)
    ingresos = cfg.get("ingresos_anuales")
    try:
        ingresos = float(ingresos) if ingresos not in (None, "", 0) else None
    except (TypeError, ValueError):
        ingresos = None
    tope_ing = round(ingresos * 0.15, 2) if ingresos else None
    tope = min(tope_uma, tope_ing) if tope_ing is not None else tope_uma
    monto = _suma(per, "Importe Base")
    return {"monto": monto, "conteo": int(len(per)), "tope_5_uma": tope_uma,
            "tope_15_ingresos": tope_ing, "tope_aplicable": tope,
            "excede": round(max(0.0, monto - tope), 2),
            "nota": ("Con ingresos_anuales vacio solo se compara contra 5 UMA; captura tus ingresos "
                     "anuales en config_reglas.json para aplicar tambien el 15 %.") if tope_ing is None else ""}


def procesar_archivos(rutas: List[str], config: Optional[Dict[str, Any]] = None,
                      origenes: Optional[Dict[str, str]] = None
                      ) -> Tuple[pd.DataFrame, Dict[str, Any], List[Dict[str, Any]]]:
    """
    Punto de entrada unico: lee N archivos (emitidas, recibidas, pagos, nominas,
    egresos), les aplica las reglas de su tipo y devuelve
    (dataframe_procesado, totales, diagnosticos_por_archivo).
    """
    cfg = config or cargar_config()
    forzados = {k.lower(): v for k, v in (origenes or {}).items()}
    marcos, diagnosticos = [], []
    marcos_xml: List[Tuple[pd.DataFrame, Dict[str, Any]]] = []

    for ruta in rutas:
        nombre = os.path.basename(ruta)
        es_xml = os.path.splitext(ruta)[1].lower() in (".xml", ".zip") or os.path.isdir(ruta)

        if es_xml:
            # Fuente XML: cada CFDI dice solo lo que es
            df_crudo, diag = leer_cfdis_xml(ruta, cfg)
            if df_crudo.empty:
                diag["avisos"].append("No se encontro ningun CFDI valido.")
                diagnosticos.append(diag)
                continue
            df_crudo["Archivo Origen"] = nombre
            diag["filas"] = int(len(df_crudo))
            diag["_forzado"] = forzados.get(nombre.lower())
            marcos_xml.append((df_crudo, diag))
            diagnosticos.append(diag)
            continue

        hojas = leer_hojas_excel(ruta, cfg)
        if not hojas:
            diagnosticos.append({"archivo": nombre, "tipo_fuente": "tabla",
                                 "avisos": ["Sin filas de datos detectadas."]})
            continue

        ignoradas = [normalizar(h) for h in cfg.get("hojas_ignoradas", []) if h]
        for df_crudo, diag in hojas:
            diag["tipo_fuente"] = "tabla"
            nombre_hoja = diag.get("hoja") or ""
            if any(p and p in normalizar(nombre_hoja) for p in ignoradas):
                diag["avisos"].append("Hoja omitida por «hojas_ignoradas».")
                diag["filas"] = 0
                diagnosticos.append(diag)
                continue

            clave_forzada = f"{nombre.lower()}::{nombre_hoja.lower()}"
            origen, como = detectar_origen(
                nombre, df_crudo,
                forzados.get(clave_forzada) or forzados.get(nombre.lower()),
                nombre_hoja=nombre_hoja)
            etiqueta = f"{nombre} › {nombre_hoja}" if len(hojas) > 1 else nombre
            df_crudo["Archivo Origen"] = etiqueta
            df_crudo["Origen"] = origen
            diag["origen"] = origen
            diag["origen_etiqueta"] = ETIQUETAS_ORIGEN.get(origen, origen)
            diag["origen_detectado_por"] = como
            diag["filas"] = int(len(df_crudo))
            if como == "contenido":
                diag["avisos"].append(
                    f"Ni la hoja ni el archivo dicen que es: se dedujo "
                    f"«{ETIQUETAS_ORIGEN[origen]}» por su contenido.")
            marcos.append(df_crudo)
            diagnosticos.append(diag)

    # Con todos los XML leidos ya se puede saber de quien es la contabilidad
    if marcos_xml:
        rfc_xml, ambiguo_xml = _asignar_origen_xml(marcos_xml, cfg)
        # Solo se exige que el receptor sea el contribuyente cuando se sabe con certeza quien es
        cfg = dict(cfg)
        cfg["_rfc_certero"] = rfc_xml if (rfc_xml and not ambiguo_xml) else ""
        for df_x, diag in marcos_xml:
            forzado = diag.pop("_forzado", None)
            if forzado:
                df_x["Origen"] = str(forzado).upper()
                diag["origen_detectado_por"] = "config_reglas.json"
            marcos.append(df_x)

    if not marcos:
        return pd.DataFrame(), calcular_totales(pd.DataFrame()), diagnosticos

    df = pd.concat(marcos, ignore_index=True, sort=False)
    df = preparar_dataframe(df, cfg)

    # Duplicados: el mismo UUID puede aparecer legitimamente en dos archivos
    # distintos (una factura en Emitidas y su REP en Pagos), asi que la llave
    # de deduplicacion es UUID + archivo de origen.
    if "UUID" in df.columns:
        antes = len(df)
        con_uuid = df["UUID"].astype(str).str.strip() != ""
        df = pd.concat([df[~con_uuid],
                        df[con_uuid].drop_duplicates(subset=["UUID", "Origen"])],
                       ignore_index=True)
        if len(df) < antes:
            diagnosticos.append({"archivo": "(global)", "avisos": [
                f"Se eliminaron {antes - len(df)} CFDI duplicados (mismo UUID en el "
                f"mismo tipo de archivo)."]})

    df["_Sustituido"] = reglas_md.marcar_sustituidos(df)
    # REP: los UUID que cada complemento de pago liquida (solo el XML los trae)
    pagados = set()
    if "UUID Relacionados" in df.columns:
        for valor in df.loc[df["Tipo Comprobante"] == "P", "UUID Relacionados"].tolist():
            if isinstance(valor, str):   # en los Excel puede venir vacio (NaN)
                pagados.update(u.strip().upper() for u in valor.split(",") if u.strip())
    df["_Tiene_REP"] = df["UUID"].astype(str).str.upper().isin(pagados)
    df["_Hay_REP_en_tanda"] = bool((df["Tipo Comprobante"] == "P").any())

    if bool(cfg.get("verificar_estatus_sat", False)):
        df, res_sat = verificar_estatus_en_sat(df, cfg)
        aviso = (f"Estatus en el SAT: {res_sat['total']} CFDI, {res_sat.get('cancelados', 0)} cancelados, "
                 f"{res_sat.get('no_encontrados', 0)} no encontrados, {res_sat['errores']} sin respuesta "
                 f"({res_sat['de_cache']} desde cache).")
        if res_sat["errores"]:
            aviso += " Los que no respondieron conservan su estatus anterior: reintenta mas tarde."
        diagnosticos.append({"archivo": "(estatus SAT)", "avisos": [aviso] + res_sat["mensajes_error"]})
        totales_sat = res_sat
    else:
        totales_sat = None

    df, tipos_cambio, avisos_tc = convertir_a_mxn(df, cfg)
    if avisos_tc:
        diagnosticos.append({"archivo": "(tipo de cambio)", "avisos": avisos_tc})

    df = aplicar_reglas(df, cfg)
    totales = calcular_totales(df)
    totales["tipos_cambio"] = tipos_cambio
    totales["estatus_sat"] = totales_sat or {}
    totales["deducciones_personales_tope"] = _tope_global_personales(df, cfg)

    # El perfil del contribuyente se arma solo con lo que traen los CFDI:
    # RFC, giro propuesto y catalogo de proveedores. No necesita credenciales.
    if bool(cfg.get("usar_perfiles", True)):
        try:
            totales["perfil"] = perfiles.resumen(perfiles.actualizar_perfil(df, cfg))
        except OSError as exc:
            diagnosticos.append({"archivo": "(perfil)",
                                 "avisos": [f"No se pudo guardar el perfil: {exc}"]})
    return df, totales, diagnosticos


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Uso: python procesador_cfdi.py <archivo.xlsx> [mas archivos...]")
        raise SystemExit(1)
    datos, tot, diags = procesar_archivos(sys.argv[1:])
    for d in diags:
        if d.get("origen"):
            print(f"- {d.get('archivo')}: [{d.get('origen_etiqueta')}] hoja={d.get('hoja')} "
                  f"encabezado en fila {d.get('fila_encabezado')} | filas={d.get('filas', 0)} "
                  f"| rojas={d.get('filas_rojas', 0)}")
        for aviso in d.get("avisos", []):
            print(f"    ! {aviso}")
    print(f"\nIngresos facturados : {tot['total_ingresos']:>15,.2f}")
    print(f"TOTAL DEDUCIBLE     : {tot['total_deducible']:>15,.2f}")
    for b in tot["bloques"]:
        print(f"  {b['etiqueta']:<24} suma {b['total']:>14,.2f}  "
              f"({b['conteo_suma']}/{b['conteo']} CFDI)")
    salida = exportar_excel(datos, tot, "Reporte_Deducibles.xlsx")
    print(f"\nExcel generado: {salida}")
