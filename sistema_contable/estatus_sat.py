# -*- coding: utf-8 -*-
"""
estatus_sat.py
--------------
Consulta en linea el estatus de cada CFDI en el SAT (servicio publico de
"Consulta de CFDI", el mismo del codigo QR de la factura). NO necesita e.firma.

Dice, por UUID:
  * Estado: Vigente / Cancelado / No Encontrado
  * EsCancelable: si se puede cancelar y con que condiciones
  * EstatusCancelacion: "En proceso", "Solicitud rechazada", "Cancelado sin aceptacion", ...
  * ValidacionEFOS: codigo de la validacion contra la lista 69-B (se muestra tal cual)

Por que importa: el XML no sabe si lo cancelaron despues de timbrarlo. Sin esto,
una factura cancelada puede colarse en la deduccion y en el IVA acreditable.

La consulta exige que RFC emisor, RFC receptor y TOTAL coincidan con el CFDI
original. Por eso debe correr con el total ORIGINAL (antes de convertir divisas).
Un "No Encontrado" puede ser un total mal capturado: se trata como ALERTA, no
como rechazo.

Cache en disco (cache_estatus_sat.json): un CFDI cancelado no vuelve a vigente,
asi que se guarda para siempre; lo vigente se vuelve a consultar pasadas
`estatus_sat_horas_cache` horas (24 por defecto).
"""
from __future__ import annotations

import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple
from xml.etree import ElementTree

import requests

SOAP_URL = "https://consultaqr.facturaelectronica.sat.gob.mx/ConsultaCFDIService.svc"
SOAP_ACTION = "http://tempuri.org/IConsultaCFDIService/Consulta"
RUTA_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache_estatus_sat.json")
_CANDADO = threading.Lock()


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def total_sat(total: float) -> str:
    """Formato que pide el SAT para el total: 10 enteros y 6 decimales."""
    return f"{abs(float(total)):017.6f}"


def _solicitud(rfc_emisor: str, rfc_receptor: str, total: float, uuid: str) -> str:
    expresion = f"?re={rfc_emisor}&rr={rfc_receptor}&tt={total_sat(total)}&id={uuid}"
    return (
        '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
        'xmlns:tem="http://tempuri.org/"><soapenv:Header/><soapenv:Body><tem:Consulta>'
        f"<tem:expresionImpresa><![CDATA[{expresion}]]></tem:expresionImpresa>"
        "</tem:Consulta></soapenv:Body></soapenv:Envelope>"
    )


def interpretar(xml_texto: str) -> Dict[str, str]:
    """Lee la respuesta SOAP del SAT. Tolera cambios de prefijo de namespace."""
    raiz = ElementTree.fromstring(xml_texto)
    datos = {"codigo_estatus": "", "es_cancelable": "", "estado": "",
             "estatus_cancelacion": "", "validacion_efos": ""}
    mapa = {"CodigoEstatus": "codigo_estatus", "EsCancelable": "es_cancelable", "Estado": "estado",
            "EstatusCancelacion": "estatus_cancelacion", "ValidacionEFOS": "validacion_efos"}
    for nodo in raiz.iter():
        clave = mapa.get(_local(nodo.tag))
        if clave:
            datos[clave] = (nodo.text or "").strip()
    return datos


def consultar(rfc_emisor: str, rfc_receptor: str, total: float, uuid: str,
              timeout: int = 15) -> Dict[str, str]:
    """Una consulta al SAT. Lanza requests.RequestException o ValueError si falla."""
    r = requests.post(
        SOAP_URL, data=_solicitud(rfc_emisor.strip().upper(), rfc_receptor.strip().upper(),
                                  total, uuid.strip().upper()).encode("utf-8"),
        headers={"Content-Type": 'text/xml;charset="utf-8"', "Accept": "text/xml",
                 "Cache-Control": "no-cache", "SOAPAction": SOAP_ACTION},
        timeout=timeout)
    if r.status_code != 200:
        raise ValueError(f"El SAT respondio HTTP {r.status_code}")
    datos = interpretar(r.text)
    if not datos["estado"]:
        raise ValueError("Respuesta del SAT sin 'Estado'")
    return datos


# -----------------------------------------------------------------------------
# Cache
# -----------------------------------------------------------------------------

def _leer_cache(ruta: str) -> Dict[str, Any]:
    try:
        with open(ruta, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _guardar_cache(ruta: str, cache: Dict[str, Any]) -> None:
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cache, fh, ensure_ascii=False)
    os.replace(tmp, ruta)


def _vigente_en_cache(entrada: Dict[str, Any], horas: float) -> bool:
    if entrada.get("estado") == "Cancelado":
        return True                      # una cancelacion es definitiva
    try:
        cuando = datetime.fromisoformat(entrada["consultado"])
    except (KeyError, ValueError):
        return False
    return datetime.now() - cuando < timedelta(hours=horas)


# -----------------------------------------------------------------------------
# Lote
# -----------------------------------------------------------------------------

def verificar_lote(cfdis: List[Dict[str, Any]], hilos: int = 4, timeout: int = 15,
                   horas_cache: float = 24, ruta_cache: str = RUTA_CACHE,
                   consultor: Callable[..., Dict[str, str]] = consultar,
                   progreso: Optional[Callable[[int, int], None]] = None
                   ) -> Tuple[Dict[str, Dict[str, str]], Dict[str, Any]]:
    """
    cfdis: [{"uuid","rfc_emisor","rfc_receptor","total"}]. Devuelve
    ({uuid: datos}, resumen). Los que fallan quedan fuera de `datos` y se
    cuentan en resumen["errores"]; nunca se inventa un estatus.
    """
    cache = _leer_cache(ruta_cache)
    resultados: Dict[str, Dict[str, str]] = {}
    pendientes: List[Dict[str, Any]] = []
    vistos = set()
    for c in cfdis:
        u = str(c.get("uuid") or "").strip().upper()
        if not u or u in vistos:
            continue
        vistos.add(u)
        if u in cache and _vigente_en_cache(cache[u], horas_cache):
            resultados[u] = {**cache[u], "origen": "cache"}
        else:
            pendientes.append({**c, "uuid": u})

    resumen = {"total": len(vistos), "de_cache": len(resultados), "consultados": 0, "errores": 0,
               "cancelados": 0, "no_encontrados": 0, "mensajes_error": []}

    def _una(c: Dict[str, Any]):
        ultimo = None
        for intento in range(3):
            try:
                return c["uuid"], consultor(c["rfc_emisor"], c["rfc_receptor"], c["total"], c["uuid"], timeout), None
            except (requests.RequestException, ValueError, ElementTree.ParseError) as exc:
                ultimo = exc
                time.sleep(0.6 * (intento + 1))
        return c["uuid"], None, ultimo

    hechos = 0
    with ThreadPoolExecutor(max_workers=max(1, int(hilos))) as pool:
        futuros = [pool.submit(_una, c) for c in pendientes]
        for fut in as_completed(futuros):
            u, datos, exc = fut.result()
            hechos += 1
            if datos:
                datos = {**datos, "consultado": datetime.now().isoformat(timespec="seconds")}
                resultados[u] = {**datos, "origen": "sat"}
                with _CANDADO:
                    cache[u] = datos
                resumen["consultados"] += 1
            else:
                resumen["errores"] += 1
                if len(resumen["mensajes_error"]) < 3:
                    resumen["mensajes_error"].append(f"{type(exc).__name__}: {exc}")
            if progreso:
                progreso(hechos, len(pendientes))
    if resumen["consultados"]:
        try:
            _guardar_cache(ruta_cache, cache)
        except OSError:
            pass
    resumen["cancelados"] = sum(1 for d in resultados.values() if d.get("estado") == "Cancelado")
    resumen["no_encontrados"] = sum(1 for d in resultados.values()
                                    if d.get("estado", "").lower().startswith("no encontrado"))
    return resultados, resumen
