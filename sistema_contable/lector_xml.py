# -*- coding: utf-8 -*-
"""
lector_xml.py
-------------
Lee CFDI en su formato original (XML 3.3 / 4.0) y los convierte a las mismas
columnas que el motor ya usa para los Excel.

Por que importa: el XML es la factura real. Trae el tipo de comprobante sin
ambiguedad, cada impuesto desglosado, la clave del catalogo del SAT de cada
concepto, y -en los complementos de pago- el UUID exacto de la factura que se
esta pagando. Nada de eso se puede deducir de un Excel de portal contable.

Acepta:
  * un .xml suelto
  * un .zip (como lo entrega la descarga masiva del SAT), incluso anidado
  * una carpeta con XML adentro

Lo que el XML NO trae: si el CFDI fue cancelado despues de timbrarse. Eso vive
solo en el SAT (servicio ConsultaCFDI) o en el archivo de metadata del ZIP.
"""
from __future__ import annotations

import os
import zipfile
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree

# Claves del catalogo de impuestos del SAT
IMPUESTO_ISR = "001"
IMPUESTO_IVA = "002"
IMPUESTO_IEPS = "003"

EXTENSIONES_XML = {".xml"}
EXTENSIONES_ZIP = {".zip"}
# Dentro de un ZIP del SAT tambien puede venir el archivo de metadata
EXTENSIONES_TABLA = {".csv", ".txt"}


# =============================================================================
# 1. UTILIDADES DE XML (sin pelearse con los namespaces)
# =============================================================================

def _local(etiqueta: str) -> str:
    """'{http://...}Comprobante' -> 'comprobante'."""
    return etiqueta.rsplit("}", 1)[-1].lower()


def _hijos(nodo, nombre: str):
    """Hijos directos cuyo nombre local coincide, sin importar el prefijo."""
    nombre = nombre.lower()
    return [h for h in list(nodo) if _local(h.tag) == nombre]


def _hijo(nodo, nombre: str):
    encontrados = _hijos(nodo, nombre)
    return encontrados[0] if encontrados else None


def _buscar_todos(nodo, nombre: str) -> List[Any]:
    """Busca en todo el arbol (a cualquier profundidad)."""
    nombre = nombre.lower()
    return [n for n in nodo.iter() if _local(n.tag) == nombre]


def _attr(nodo, *nombres: str) -> str:
    """Atributo tolerante a mayusculas: _attr(n, 'Rfc') encuentra 'RFC' y 'rfc'."""
    if nodo is None:
        return ""
    for nombre in nombres:
        if nombre in nodo.attrib:
            return str(nodo.attrib[nombre]).strip()
    bajos = {k.lower(): v for k, v in nodo.attrib.items()}
    for nombre in nombres:
        if nombre.lower() in bajos:
            return str(bajos[nombre.lower()]).strip()
    return ""


def _num(valor: Any) -> float:
    try:
        return float(str(valor).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def _fecha(texto: str) -> Optional[datetime]:
    if not texto:
        return None
    texto = texto.strip().replace("Z", "")
    for formato in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d"):
        try:
            return datetime.strptime(texto[:26], formato)
        except ValueError:
            continue
    return None


# =============================================================================
# 2. LECTURA DE UN CFDI
# =============================================================================

def leer_cfdi(contenido: bytes, nombre: str = "") -> Optional[Dict[str, Any]]:
    """Convierte el XML de un CFDI al diccionario de columnas del motor."""
    try:
        raiz = ElementTree.fromstring(contenido)
    except ElementTree.ParseError:
        return None
    if _local(raiz.tag) != "comprobante":
        return None

    emisor = _hijo(raiz, "Emisor")
    receptor = _hijo(raiz, "Receptor")

    reg: Dict[str, Any] = {
        "Version CFDI": _attr(raiz, "Version", "version"),
        "Serie": _attr(raiz, "Serie"),
        "Folio": _attr(raiz, "Folio"),
        "Fecha Emision": _fecha(_attr(raiz, "Fecha")),
        "Tipo Comprobante": _attr(raiz, "TipoDeComprobante").upper()[:1],
        "Forma Pago": _attr(raiz, "FormaPago"),
        "Metodo Pago": _attr(raiz, "MetodoPago"),
        "Moneda": _attr(raiz, "Moneda") or "MXN",
        "Tipo Cambio CFDI": _num(_attr(raiz, "TipoCambio")),
        "Subtotal": _num(_attr(raiz, "SubTotal")),
        "Descuento": _num(_attr(raiz, "Descuento")),
        "Total": _num(_attr(raiz, "Total")),
        "Lugar Expedicion": _attr(raiz, "LugarExpedicion"),
        "RFC Emisor": _attr(emisor, "Rfc").upper(),
        "Nombre Emisor": _attr(emisor, "Nombre"),
        "Regimen Emisor": _attr(emisor, "RegimenFiscal"),
        "RFC Receptor": _attr(receptor, "Rfc").upper(),
        "Nombre Receptor": _attr(receptor, "Nombre"),
        "Regimen Receptor": _attr(receptor, "RegimenFiscalReceptor"),
        "Uso CFDI": _attr(receptor, "UsoCFDI"),
        # El XML no sabe si lo cancelaron despues. Se asume vigente y se corrige
        # con el archivo de metadata del ZIP o con el servicio ConsultaCFDI.
        "Estatus": "Vigente",
        "Archivo XML": nombre,
    }

    # --- CFDI relacionados (notas de credito, sustituciones, anticipos) ---
    # Tipo de relacion: 01 nota de credito, 03 devolucion, 04 SUSTITUCION, 07 anticipo
    tipos_rel: List[str] = []
    uuids_rel: List[str] = []
    sustituidos: List[str] = []
    for nodo_rel in _hijos(raiz, "CfdiRelacionados"):
        tipo_rel = _attr(nodo_rel, "TipoRelacion")
        if tipo_rel and tipo_rel not in tipos_rel:
            tipos_rel.append(tipo_rel)
        for rel in _hijos(nodo_rel, "CfdiRelacionado"):
            u = _attr(rel, "UUID").upper()
            if u:
                uuids_rel.append(u)
                if tipo_rel == "04":
                    sustituidos.append(u)
    reg["Tipo Relacion"] = ",".join(tipos_rel)
    reg["CFDI Relacionados"] = ",".join(uuids_rel)
    reg["UUID Sustituidos"] = ",".join(sustituidos)
    reg["CP Receptor"] = _attr(receptor, "DomicilioFiscalReceptor")
    reg["Factura Global"] = _hijo(raiz, "InformacionGlobal") is not None

    # --- UUID (timbre fiscal digital) ------------------------------------
    timbre = next(iter(_buscar_todos(raiz, "TimbreFiscalDigital")), None)
    reg["UUID"] = _attr(timbre, "UUID").upper()
    reg["Fecha Timbrado"] = _fecha(_attr(timbre, "FechaTimbrado"))

    # --- Conceptos: descripcion y claves del catalogo SAT -----------------
    conceptos = _buscar_todos(raiz, "Concepto")
    descripciones, claves = [], []
    for c in conceptos:
        desc = _attr(c, "Descripcion")
        if desc:
            descripciones.append(desc)
        clave = _attr(c, "ClaveProdServ")
        if clave and clave not in claves:
            claves.append(clave)
    reg["Descripcion"] = " | ".join(descripciones[:8])
    reg["Claves ProdServ"] = ",".join(claves)
    reg["Conceptos"] = len(conceptos)

    # --- Impuestos del comprobante ---------------------------------------
    reg.update(_impuestos(raiz))

    # --- Complementos -----------------------------------------------------
    reg.update(_complemento_nomina(raiz))
    reg.update(_complemento_pagos(raiz, reg))

    return reg


def _impuestos(raiz) -> Dict[str, float]:
    """IVA / IEPS trasladados y IVA / ISR retenidos, del nodo Impuestos global."""
    datos = {"IVA": 0.0, "IEPS": 0.0, "IVA Retenido": 0.0,
             "ISR Retenido": 0.0, "Retenciones": 0.0}

    nodo = None
    for candidato in _hijos(raiz, "Impuestos"):
        nodo = candidato
        break
    if nodo is None:
        return datos

    datos["Retenciones"] = _num(_attr(nodo, "TotalImpuestosRetenidos"))

    traslados = _hijo(nodo, "Traslados")
    if traslados is not None:
        for t in _hijos(traslados, "Traslado"):
            impuesto = _attr(t, "Impuesto")
            importe = _num(_attr(t, "Importe"))
            if impuesto == IMPUESTO_IVA:
                datos["IVA"] += importe
            elif impuesto == IMPUESTO_IEPS:
                datos["IEPS"] += importe

    retenciones = _hijo(nodo, "Retenciones")
    if retenciones is not None:
        for r in _hijos(retenciones, "Retencion"):
            impuesto = _attr(r, "Impuesto")
            importe = _num(_attr(r, "Importe"))
            if impuesto == IMPUESTO_IVA:
                datos["IVA Retenido"] += importe
            elif impuesto == IMPUESTO_ISR:
                datos["ISR Retenido"] += importe

    if not datos["Retenciones"]:
        datos["Retenciones"] = datos["IVA Retenido"] + datos["ISR Retenido"]
    return {k: round(v, 2) for k, v in datos.items()}


def _complemento_nomina(raiz) -> Dict[str, Any]:
    nomina = next(iter(_buscar_todos(raiz, "Nomina")), None)
    if nomina is None:
        return {"Percepciones": 0.0, "Deducciones": 0.0, "Otros Pagos": 0.0}
    return {
        "Percepciones": _num(_attr(nomina, "TotalPercepciones")),
        "Deducciones": _num(_attr(nomina, "TotalDeducciones")),
        "Otros Pagos": _num(_attr(nomina, "TotalOtrosPagos")),
        "Dias Pagados": _attr(nomina, "NumDiasPagados"),
        "Periodo Pago": f"{_attr(nomina, 'FechaInicialPago')} a {_attr(nomina, 'FechaFinalPago')}".strip(" a"),
    }


def _complemento_pagos(raiz, reg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Complemento de pago (REP). Aqui esta lo que ningun Excel trae:
    el UUID de cada factura que este pago liquida, y cuanto le abono.
    """
    pagos = _buscar_todos(raiz, "Pago")
    if not pagos:
        return {"Monto Pagado": 0.0, "UUID Relacionados": "", "Documentos Pagados": 0}

    monto = 0.0
    relacionados: List[str] = []
    detalle: List[Dict[str, Any]] = []
    formas: List[str] = []

    for pago in pagos:
        monto += _num(_attr(pago, "Monto"))
        forma = _attr(pago, "FormaDePagoP")
        if forma and forma not in formas:
            formas.append(forma)
        for doc in _buscar_todos(pago, "DoctoRelacionado"):
            uuid = _attr(doc, "IdDocumento").upper()
            if uuid:
                relacionados.append(uuid)
            detalle.append({
                "uuid": uuid,
                "serie": _attr(doc, "Serie"),
                "folio": _attr(doc, "Folio"),
                "parcialidad": _attr(doc, "NumParcialidad"),
                "saldo_anterior": _num(_attr(doc, "ImpSaldoAnt")),
                "pagado": _num(_attr(doc, "ImpPagado")),
                "saldo_insoluto": _num(_attr(doc, "ImpSaldoInsoluto")),
            })

    salida: Dict[str, Any] = {
        "Monto Pagado": round(monto, 2),
        "UUID Relacionados": ",".join(relacionados),
        "Documentos Pagados": len(detalle),
        "_Pagos_Detalle": detalle,
    }
    # En un REP la forma de pago vive en el complemento, no en el comprobante
    if not reg.get("Forma Pago") and formas:
        salida["Forma Pago"] = formas[0]
    return salida


# =============================================================================
# 3. RECOLECCION: XML SUELTO, ZIP (ANIDADO) O CARPETA
# =============================================================================

def recolectar(ruta: str, diag: Optional[Dict[str, Any]] = None
               ) -> Tuple[List[Dict[str, Any]], List[Tuple[str, bytes]]]:
    """
    Devuelve (cfdis_leidos, tablas_encontradas).
    `tablas_encontradas` son los .csv/.txt de metadata que vengan dentro del ZIP.
    """
    diag = diag if diag is not None else {}
    cfdis: List[Dict[str, Any]] = []
    tablas: List[Tuple[str, bytes]] = []
    ext = os.path.splitext(ruta)[1].lower()

    if os.path.isdir(ruta):
        for raiz_dir, _, archivos in os.walk(ruta):
            for nombre in archivos:
                sub, subtab = recolectar(os.path.join(raiz_dir, nombre), diag)
                cfdis.extend(sub)
                tablas.extend(subtab)
        return cfdis, tablas

    if ext in EXTENSIONES_XML:
        with open(ruta, "rb") as fh:
            reg = leer_cfdi(fh.read(), os.path.basename(ruta))
        if reg:
            cfdis.append(reg)
        else:
            diag.setdefault("ignorados", []).append(os.path.basename(ruta))
        return cfdis, tablas

    if ext in EXTENSIONES_ZIP:
        cfdis, tablas = _recolectar_zip(ruta, diag)
        return cfdis, tablas

    return cfdis, tablas


def _recolectar_zip(ruta: str, diag: Dict[str, Any], profundidad: int = 0
                    ) -> Tuple[List[Dict[str, Any]], List[Tuple[str, bytes]]]:
    cfdis: List[Dict[str, Any]] = []
    tablas: List[Tuple[str, bytes]] = []
    if profundidad > 3:
        return cfdis, tablas
    try:
        zf = zipfile.ZipFile(ruta)
    except (zipfile.BadZipFile, OSError) as exc:
        diag.setdefault("avisos", []).append(f"No se pudo abrir el ZIP: {exc}")
        return cfdis, tablas

    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            nombre = os.path.basename(info.filename)
            ext = os.path.splitext(nombre)[1].lower()
            try:
                datos = zf.read(info)
            except (zipfile.BadZipFile, OSError):
                continue
            if ext in EXTENSIONES_XML:
                reg = leer_cfdi(datos, nombre)
                if reg:
                    cfdis.append(reg)
                else:
                    diag.setdefault("ignorados", []).append(nombre)
            elif ext in EXTENSIONES_TABLA:
                tablas.append((nombre, datos))
            elif ext in EXTENSIONES_ZIP:
                # La descarga masiva a veces entrega ZIP dentro de ZIP
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
                    tmp.write(datos)
                    tmp_ruta = tmp.name
                try:
                    sub, subtab = _recolectar_zip(tmp_ruta, diag, profundidad + 1)
                    cfdis.extend(sub)
                    tablas.extend(subtab)
                finally:
                    try:
                        os.unlink(tmp_ruta)
                    except OSError:
                        pass
    return cfdis, tablas


# =============================================================================
# 4. DE QUE ARCHIVO VIENE CADA CFDI
# =============================================================================

def rfc_del_contribuyente(cfdis: List[Dict[str, Any]]) -> Tuple[str, bool]:
    """
    El contribuyente es el RFC que aparece en TODOS los comprobantes, sea como
    emisor o como receptor. Hay que mirar la tanda completa: con un solo CFDI
    es imposible saber si es emitida o recibida.

    Devuelve (rfc, ambiguo).
    """
    total = len(cfdis)
    conteo: Dict[str, int] = {}
    for reg in cfdis:
        vistos = set()
        for clave in ("RFC Emisor", "RFC Receptor"):
            rfc = (reg.get(clave) or "").strip().upper()
            if rfc and rfc != "XAXX010101000":
                vistos.add(rfc)
        for rfc in vistos:
            conteo[rfc] = conteo.get(rfc, 0) + 1
    if not conteo:
        return "", True

    maximo = max(conteo.values())
    candidatos = sorted(r for r, n in conteo.items() if n == maximo)
    ambiguo = len(candidatos) > 1 or maximo < total
    return candidatos[0], ambiguo


def origen_de(reg: Dict[str, Any], rfc_contribuyente: str) -> str:
    """Nominas y Pagos se delatan por su tipo; el resto, por de quien es el RFC."""
    tipo = (reg.get("Tipo Comprobante") or "").upper()
    if tipo == "N":
        return "NOMINAS"
    if tipo == "P":
        return "PAGOS"
    if rfc_contribuyente:
        if (reg.get("RFC Emisor") or "").upper() == rfc_contribuyente:
            return "EMITIDAS"
        if (reg.get("RFC Receptor") or "").upper() == rfc_contribuyente:
            return "RECIBIDAS"
    return "RECIBIDAS"
