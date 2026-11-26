# -*- coding: utf-8 -*-
"""
app.py — Servidor local Flask del Sistema Contable (auditoria de CFDI 4.0).

Ejecutar:   python app.py
Abrir:      http://127.0.0.1:5000
"""
from __future__ import annotations

import os
import shutil
import tempfile
import traceback
import uuid as uuid_lib
from datetime import datetime, timedelta
from typing import Any, Dict, List

import pandas as pd
from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.utils import secure_filename

from boveda import Boveda, BovedaError
from descarga_sat import DescargaError, DescargaSAT
from procesador_cfdi import (ETIQUETAS_ORIGEN, ORDEN_ORIGENES, cargar_config,
                             exportar_excel, procesar_archivos, sumar_por_moneda)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CARPETA_TRABAJO = os.path.join(tempfile.gettempdir(), "sistema_contable_cfdi")
EXTENSIONES = {".xlsx", ".xlsm", ".xls", ".csv", ".xml", ".zip"}
MAX_MB = 64
LIMITE_PREVIA = 500          # filas que se pintan por pestaña en el navegador
VIDA_RESULTADO = timedelta(hours=6)

# Columnas de la tabla del dashboard, en orden de lectura.
# El navegador esconde solas las columnas de importe que van en ceros.
COLUMNAS_TABLA = [
    "Origen", "Archivo Origen", "UUID", "Fecha Emision",
    "RFC Emisor", "Nombre Emisor", "RFC Receptor", "Nombre Receptor",
    "Tipo Comprobante", "Tipo Comprobante Desc", "Uso CFDI", "Uso CFDI Desc",
    "Forma Pago", "Forma Pago Desc", "Metodo Pago", "Metodo Pago Desc",
    "Descripcion", "Claves ProdServ", "UUID Relacionados",
    "Moneda Original", "Tipo de Cambio", "Total Original",
    "Subtotal", "Descuento", "IVA", "IEPS",
    "IVA Retenido", "ISR Retenido", "Retenciones",
    "Percepciones", "Deducciones", "Otros Pagos",
    "Total", "Monto Pagado", "Importe Computado", "IVA Acreditable",
]
COLUMNAS_RESULTADO = ["Clasificacion", "Regla Aplicada", "Motivo de Rechazo", "Alertas"]

os.makedirs(CARPETA_TRABAJO, exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_MB * 1024 * 1024
# Sin esto, Flask fuera de modo debug cachea index.html y los cambios de la
# interfaz no se ven hasta reiniciar el servidor.
app.config["TEMPLATES_AUTO_RELOAD"] = True

RESULTADOS: Dict[str, Dict[str, Any]] = {}


# ---- Boveda de e.firma y descarga del SAT ---------------------------------
def _ruta_boveda() -> str:
    ruta = str(cargar_config().get("ruta_boveda") or os.path.join("boveda", "boveda.enc"))
    return ruta if os.path.isabs(ruta) else os.path.join(BASE_DIR, ruta)


_cfg0 = cargar_config()
BOVEDA = Boveda(_ruta_boveda(), float(_cfg0.get("boveda_minutos_inactividad", 15)))
_carpeta_desc = str(_cfg0.get("carpeta_descargas") or "descargas")
DESCARGA = DescargaSAT(BOVEDA, _carpeta_desc if os.path.isabs(_carpeta_desc)
                       else os.path.join(BASE_DIR, _carpeta_desc))
HOSTS_OK = {"127.0.0.1", "localhost", "[::1]"}


@app.before_request
def _guardia():
    """
    Las rutas de boveda y de SAT manejan e.firma: solo se aceptan desde esta misma pagina.
      * Host local (evita 'DNS rebinding': una pagina ajena que apunta a 127.0.0.1).
      * Cabecera propia X-Sistema (un sitio ajeno no puede mandarla sin permiso CORS).
    """
    if request.path.startswith(("/boveda/", "/sat/", "/resultado/")):
        host = (request.host or "").rsplit(":", 1)[0]
        if host not in HOSTS_OK:
            return jsonify({"ok": False, "error": "Host no permitido."}), 403
        if request.headers.get("X-Sistema") != "1":
            return jsonify({"ok": False, "error": "Solicitud no autorizada."}), 403


def _error(exc: Exception, codigo: int = 400):
    return jsonify({"ok": False, "error": str(exc)}), codigo


def _extension_valida(nombre: str) -> bool:
    return os.path.splitext(nombre)[1].lower() in EXTENSIONES


def _purgar() -> None:
    """Suelta los resultados viejos para que la memoria no crezca sin freno."""
    limite = datetime.now() - VIDA_RESULTADO
    for clave in [k for k, v in RESULTADOS.items() if v.get("creado", datetime.now()) < limite]:
        shutil.rmtree(os.path.dirname(RESULTADOS[clave]["excel"]), ignore_errors=True)
        RESULTADOS.pop(clave, None)


def _previa(df: pd.DataFrame, columnas: List[str], limite: int = LIMITE_PREVIA):
    """DataFrame -> lista de dicts serializable para el frontend."""
    if df.empty:
        return []
    cols = [c for c in columnas if c in df.columns]
    vista = df[cols].head(limite).copy()
    if "Fecha Emision" in vista.columns:
        vista["Fecha Emision"] = pd.to_datetime(
            vista["Fecha Emision"], errors="coerce").dt.strftime("%d/%m/%Y").fillna("")
    if "_Suma" in df.columns:
        vista["_Suma"] = df["_Suma"].head(limite).astype(bool).values
    return vista.fillna("").astype(object).to_dict(orient="records")


def _tabla(df: pd.DataFrame, etiqueta: str, columnas: List[str]) -> Dict[str, Any]:
    """Arma una pestaña: filas visibles + totales calculados sobre TODAS las filas."""
    return {
        "etiqueta": etiqueta,
        "conteo": int(len(df)),
        "filas": _previa(df, columnas),
        "totales": sumar_por_moneda(df),
        "totales_suma": sumar_por_moneda(df[df["_Suma"]]) if "_Suma" in df.columns else [],
    }


@app.route("/")
def inicio():
    return render_template("index.html")


@app.route("/config", methods=["GET"])
def ver_config():
    return jsonify(cargar_config())


def _responder(rutas: List[str], id_sesion: str, carpeta: str, cfg: Dict[str, Any]):
    """Procesa las rutas, arma el Excel y la respuesta del dashboard."""
    df, totales, diagnosticos = procesar_archivos(rutas, cfg)

    if df.empty:
        return jsonify({"ok": False,
                        "error": "No se detectaron filas de CFDI en los archivos.",
                        "diagnosticos": diagnosticos}), 422

    nombre_excel = f"Reporte_CFDI_{datetime.now():%Y%m%d_%H%M}.xlsx"
    ruta_excel = os.path.join(carpeta, nombre_excel)
    exportar_excel(df, totales, ruta_excel)

    cols = COLUMNAS_TABLA + COLUMNAS_RESULTADO

    # Una pestaña por archivo cargado, mas las vistas transversales
    tablas: Dict[str, Dict[str, Any]] = {}
    orden: List[str] = []
    for origen in ORDEN_ORIGENES:
        sub = df[df["Origen"] == origen]
        if sub.empty:
            continue
        tablas[origen] = _tabla(sub, ETIQUETAS_ORIGEN.get(origen, origen), cols)
        orden.append(origen)

    fuera = df[~df["_Suma"]]
    if not fuera.empty:
        tablas["NO_SUMAN"] = _tabla(fuera, "No suman", cols)
        orden.append("NO_SUMAN")

    revisar = df[df["_Conflicto_Color"] == True] if "_Conflicto_Color" in df.columns \
        else df.iloc[0:0]
    if not revisar.empty:
        tablas["REVISAR"] = _tabla(revisar, "Revisar color", cols)
        orden.append("REVISAR")

    tablas["TODO"] = _tabla(df, "Todo", cols)
    orden.append("TODO")

    payload = {
        "ok": True,
        "id_sesion": id_sesion,
        "archivo_excel": nombre_excel,
        "totales": totales,
        "diagnosticos": diagnosticos,
        "limite_previa": LIMITE_PREVIA,
        "orden_tablas": orden,
        "tablas": tablas,
    }
    RESULTADOS[id_sesion] = {"excel": ruta_excel, "totales": totales,
                             "creado": datetime.now(), "respuesta": payload}
    return jsonify(payload)


def _config_de_la_peticion() -> Dict[str, Any]:
    cfg = cargar_config()
    if request.form.get("verificar_estatus_sat") == "1":
        cfg["verificar_estatus_sat"] = True
    return cfg


@app.route("/procesar", methods=["POST"])
def procesar():
    archivos = request.files.getlist("archivos")
    if not archivos or all(not f.filename for f in archivos):
        return jsonify({"ok": False, "error": "No se recibio ningun archivo."}), 400

    _purgar()
    id_sesion = uuid_lib.uuid4().hex[:12]
    carpeta = os.path.join(CARPETA_TRABAJO, id_sesion)
    os.makedirs(carpeta, exist_ok=True)
    rutas: List[str] = []

    try:
        for f in archivos:
            if not f.filename:
                continue
            if not _extension_valida(f.filename):
                return jsonify({"ok": False,
                                "error": f"Extension no soportada: {f.filename}"}), 400
            seguro = secure_filename(f.filename) or f"archivo_{len(rutas) + 1}.xlsx"
            destino = os.path.join(carpeta, seguro)
            n = 1
            while os.path.exists(destino):   # dos archivos con el mismo nombre normalizado
                raiz, ext = os.path.splitext(seguro)
                destino = os.path.join(carpeta, f"{raiz}_{n}{ext}")
                n += 1
            f.save(destino)
            rutas.append(destino)
        return _responder(rutas, id_sesion, carpeta, _config_de_la_peticion())

    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500


@app.route("/resultado/<id_sesion>")
def resultado(id_sesion: str):
    """Reentrega un resultado ya procesado (para abrirlo en el dashboard)."""
    dato = RESULTADOS.get(id_sesion)
    if not dato:
        return jsonify({"ok": False, "error": "Resultado no disponible. Procesa de nuevo."}), 404
    return jsonify(dato["respuesta"])


# ---- Pantalla de contribuyentes -------------------------------------------
@app.route("/contribuyentes")
def pagina_contribuyentes():
    return render_template("contribuyentes.html")


@app.route("/boveda/estado")
def boveda_estado():
    return jsonify({"ok": True, "existe": BOVEDA.existe(), "abierta": BOVEDA.abierta(),
                    "ruta": BOVEDA.ruta, "minutos_inactividad": BOVEDA.minutos})


@app.route("/boveda/crear", methods=["POST"])
def boveda_crear():
    try:
        BOVEDA.crear(str((request.get_json(silent=True) or {}).get("frase", "")))
        return jsonify({"ok": True})
    except BovedaError as exc:
        return _error(exc)


@app.route("/boveda/abrir", methods=["POST"])
def boveda_abrir():
    try:
        BOVEDA.desbloquear(str((request.get_json(silent=True) or {}).get("frase", "")))
        return jsonify({"ok": True})
    except BovedaError as exc:
        return _error(exc, 401)


@app.route("/boveda/cerrar", methods=["POST"])
def boveda_cerrar():
    BOVEDA.bloquear()
    return jsonify({"ok": True})


@app.route("/boveda/lista")
def boveda_lista():
    try:
        return jsonify({"ok": True, "contribuyentes": BOVEDA.listar()})
    except BovedaError as exc:
        return _error(exc, 401)


@app.route("/boveda/agregar", methods=["POST"])
def boveda_agregar():
    cer, key = request.files.get("cer"), request.files.get("key")
    if not cer or not key:
        return _error(BovedaError("Faltan el archivo .cer o el .key."))
    try:
        info = BOVEDA.agregar(cer.read(), key.read(), request.form.get("password", ""),
                              rfc=request.form.get("rfc", ""), nombre=request.form.get("nombre", ""),
                              notas=request.form.get("notas", ""),
                              permitir_vencida=request.form.get("permitir_vencida") == "1")
        return jsonify({"ok": True, "contribuyente": info})
    except BovedaError as exc:
        return _error(exc)


@app.route("/boveda/revelar", methods=["POST"])
def boveda_revelar():
    d = request.get_json(silent=True) or {}
    try:
        return jsonify({"ok": True, "password": BOVEDA.revelar_password(str(d.get("rfc", "")), str(d.get("frase", "")))})
    except BovedaError as exc:
        return _error(exc, 401)


@app.route("/boveda/eliminar", methods=["POST"])
def boveda_eliminar():
    try:
        BOVEDA.eliminar(str((request.get_json(silent=True) or {}).get("rfc", "")))
        return jsonify({"ok": True})
    except BovedaError as exc:
        return _error(exc)


@app.route("/boveda/bitacora")
def boveda_bitacora():
    try:
        return jsonify({"ok": True, "bitacora": BOVEDA.bitacora(100)})
    except BovedaError as exc:
        return _error(exc, 401)


# ---- Descarga masiva del SAT ----------------------------------------------
@app.route("/sat/solicitar", methods=["POST"])
def sat_solicitar():
    d = request.get_json(silent=True) or {}
    try:
        desde = datetime.strptime(str(d.get("desde", "")), "%Y-%m-%d").date()
        hasta = datetime.strptime(str(d.get("hasta", "")), "%Y-%m-%d").date()
    except ValueError:
        return _error(DescargaError("Captura las fechas como AAAA-MM-DD."))
    try:
        e = DESCARGA.solicitar(str(d.get("rfc", "")), desde, hasta, str(d.get("tipo", "recibidos")),
                               str(d.get("formato", "CFDI")), d.get("estado") or None)
        return jsonify({"ok": True, "solicitud": e})
    except DescargaError as exc:
        return _error(exc)


@app.route("/sat/solicitudes")
def sat_solicitudes():
    return jsonify({"ok": True, "solicitudes": DESCARGA.listar(request.args.get("rfc") or None)})


@app.route("/sat/verificar", methods=["POST"])
def sat_verificar():
    try:
        return jsonify({"ok": True, "solicitud": DESCARGA.verificar(str((request.get_json(silent=True) or {}).get("id", "")))})
    except DescargaError as exc:
        return _error(exc)


@app.route("/sat/descargar", methods=["POST"])
def sat_descargar():
    try:
        return jsonify({"ok": True, "solicitud": DESCARGA.descargar(str((request.get_json(silent=True) or {}).get("id", "")))})
    except DescargaError as exc:
        return _error(exc)


@app.route("/sat/procesar", methods=["POST"])
def sat_procesar():
    """Procesa los ZIP ya descargados de una o varias solicitudes, con el motor de siempre."""
    d = request.get_json(silent=True) or {}
    try:
        rutas = DESCARGA.rutas_zip([str(i) for i in d.get("ids", [])])
    except DescargaError as exc:
        return _error(exc)
    _purgar()
    id_sesion = uuid_lib.uuid4().hex[:12]
    carpeta = os.path.join(CARPETA_TRABAJO, id_sesion)
    os.makedirs(carpeta, exist_ok=True)
    cfg = cargar_config()
    if d.get("verificar_estatus_sat"):
        cfg["verificar_estatus_sat"] = True
    if d.get("rfc"):
        cfg["rfc_contribuyente"] = str(d["rfc"]).upper()
    try:
        return _responder(rutas, id_sesion, carpeta, cfg)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return jsonify({"ok": False, "error": f"{type(exc).__name__}: {exc}"}), 500


@app.route("/descargar/<id_sesion>")
def descargar(id_sesion: str):
    dato = RESULTADOS.get(id_sesion)
    if not dato or not os.path.exists(dato["excel"]):
        return jsonify({"ok": False, "error": "Resultado no disponible. Procesa de nuevo."}), 404
    return send_file(dato["excel"], as_attachment=True,
                     download_name=os.path.basename(dato["excel"]))


@app.route("/limpiar", methods=["POST"])
def limpiar():
    shutil.rmtree(CARPETA_TRABAJO, ignore_errors=True)
    os.makedirs(CARPETA_TRABAJO, exist_ok=True)
    RESULTADOS.clear()
    return jsonify({"ok": True})


@app.errorhandler(413)
def demasiado_grande(_):
    return jsonify({"ok": False, "error": f"Archivo mayor a {MAX_MB} MB."}), 413


if __name__ == "__main__":
    print("=" * 62)
    print("  SISTEMA CONTABLE - Auditor de CFDI 4.0")
    print("  Abre en tu navegador:  http://127.0.0.1:5000")
    print("=" * 62)
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=False)
