# -*- coding: utf-8 -*-
"""
tipo_cambio.py
--------------
Conversion de divisas a pesos mexicanos para el Sistema Contable.

Todo el dashboard trabaja en MXN. Cuando un CFDI viene en USD, EUR, etc. se
convierte aqui y se conserva SIEMPRE el importe original en su divisa para que
la conversion sea auditable.

Fuentes, en orden:
  1. `tipos_cambio_fijos` de config_reglas.json  (lo que el contador capture a mano,
     tipicamente el tipo de cambio DOF -- es el unico con validez fiscal).
  2. API de mercado:
       * modo "fecha"  -> frankfurter.app, tasa del dia del CFDI (referencia BCE).
       * modo "actual" -> open.er-api.com, tasa de hoy.
  3. Cache en disco (tipo_cambio_cache.json): permite trabajar sin internet.

AVISO FISCAL: las tasas de las APIs son de mercado, NO son el tipo de cambio DOF
que exige el Art. 20 del CFF para efectos fiscales. Para la declaracion, captura
el DOF en `tipos_cambio_fijos`. El sistema avisa cual fuente uso en cada corrida.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import date, datetime
from typing import Any, Dict, Optional, Tuple

MONEDA_BASE = "MXN"
RUTA_CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "tipo_cambio_cache.json")
TIEMPO_ESPERA = 8
AGENTE = "SistemaContable-CFDI/1.0"

# Tasas de emergencia si no hay internet, ni cache, ni captura manual.
# Solo evitan que el sistema se caiga; el dashboard las marca como NO CONFIABLES.
TASAS_EMERGENCIA = {"USD": 17.0, "EUR": 19.7, "CAD": 12.5, "GBP": 22.5, "JPY": 0.115}


def _leer_cache() -> Dict[str, Any]:
    if not os.path.exists(RUTA_CACHE):
        return {}
    try:
        with open(RUTA_CACHE, "r", encoding="utf-8") as fh:
            datos = json.load(fh)
        return datos if isinstance(datos, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _guardar_cache(cache: Dict[str, Any]) -> None:
    try:
        with open(RUTA_CACHE, "w", encoding="utf-8") as fh:
            json.dump(cache, fh, indent=2, ensure_ascii=False)
    except OSError:
        pass


def _pedir_json(url: str) -> Optional[Dict[str, Any]]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": AGENTE})
        with urllib.request.urlopen(req, timeout=TIEMPO_ESPERA) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def _tasa_de_mercado(moneda: str, dia: Optional[str]) -> Tuple[Optional[float], str, str]:
    """Devuelve (tasa, fuente, fecha_de_la_tasa). tasa = cuantos MXN vale 1 unidad."""
    if dia:
        datos = _pedir_json(f"https://api.frankfurter.app/{dia}"
                            f"?base={moneda}&symbols={MONEDA_BASE}")
        if datos and datos.get("rates", {}).get(MONEDA_BASE):
            return (float(datos["rates"][MONEDA_BASE]),
                    "frankfurter.app (referencia BCE)", str(datos.get("date", dia)))

    datos = _pedir_json(f"https://open.er-api.com/v6/latest/{moneda}")
    if datos and datos.get("rates", {}).get(MONEDA_BASE):
        fecha = str(datos.get("time_last_update_utc", ""))[:16] or str(date.today())
        return float(datos["rates"][MONEDA_BASE]), "open.er-api.com (mercado)", fecha

    datos = _pedir_json(f"https://api.frankfurter.app/latest"
                        f"?base={moneda}&symbols={MONEDA_BASE}")
    if datos and datos.get("rates", {}).get(MONEDA_BASE):
        return (float(datos["rates"][MONEDA_BASE]),
                "frankfurter.app (referencia BCE)", str(datos.get("date", "")))

    return None, "", ""


def obtener_tasa(moneda: str, config: Dict[str, Any],
                 fecha: Optional[Any] = None) -> Dict[str, Any]:
    """
    Tasa para convertir `moneda` -> MXN.
    Devuelve {tasa, fuente, fecha, confiable}.
    """
    moneda = (moneda or MONEDA_BASE).upper()
    if moneda == MONEDA_BASE:
        return {"tasa": 1.0, "fuente": "moneda base", "fecha": "", "confiable": True}

    # 1) Captura manual (tipo de cambio DOF) -- manda sobre todo lo demas
    fijos = {k.upper(): v for k, v in (config.get("tipos_cambio_fijos") or {}).items()}
    if moneda in fijos:
        try:
            return {"tasa": float(fijos[moneda]),
                    "fuente": "capturado en config_reglas.json (DOF)",
                    "fecha": "", "confiable": True}
        except (TypeError, ValueError):
            pass

    modo = str(config.get("modo_tipo_cambio", "actual")).lower()
    dia = None
    if modo == "fecha" and fecha is not None:
        try:
            dia = (fecha.date() if isinstance(fecha, datetime) else fecha).isoformat()
        except AttributeError:
            dia = None

    cache = _leer_cache()
    clave = f"{moneda}:{dia or 'actual'}"

    # 2) Mercado
    tasa, fuente, fecha_tasa = _tasa_de_mercado(moneda, dia)
    if tasa:
        cache[clave] = {"tasa": tasa, "fuente": fuente, "fecha": fecha_tasa,
                        "consultado": datetime.now().isoformat(timespec="seconds")}
        _guardar_cache(cache)
        return {"tasa": tasa, "fuente": fuente, "fecha": fecha_tasa, "confiable": True}

    # 3) Cache (sin internet)
    guardado = cache.get(clave) or cache.get(f"{moneda}:actual")
    if guardado:
        return {"tasa": float(guardado["tasa"]),
                "fuente": f"cache local del {guardado.get('consultado', '')[:10]} (sin conexion)",
                "fecha": guardado.get("fecha", ""), "confiable": False}

    # 4) Emergencia
    if moneda in TASAS_EMERGENCIA:
        return {"tasa": TASAS_EMERGENCIA[moneda],
                "fuente": "valor de emergencia - NO CONFIABLE, capturalo a mano",
                "fecha": "", "confiable": False}

    return {"tasa": None, "fuente": "sin tipo de cambio disponible",
            "fecha": "", "confiable": False}


def tasas_para(monedas, config: Dict[str, Any],
               fechas: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
    """Resuelve de una sola vez la tasa de cada moneda presente en la corrida."""
    fechas = fechas or {}
    salida: Dict[str, Dict[str, Any]] = {}
    for moneda in sorted({(m or MONEDA_BASE).upper() for m in monedas}):
        salida[moneda] = obtener_tasa(moneda, config, fechas.get(moneda))
    return salida
