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

        df, totales, diagnosticos = procesar_archivos(rutas)

        if df.empty:
            return jsonify({"ok": False,
                            "error": "No se detectaron filas de CFDI en los archivos.",
                            "diagnosticos": diagnosticos}), 422

        nombre_excel = f"Reporte_CFDI_{datetime.now():%Y%m%d_%H%M}.xlsx"
        ruta_excel = os.path.join(carpeta, nombre_excel)
        exportar_excel(df, totales, ruta_excel)
        RESULTADOS[id_sesion] = {"excel": ruta_excel, "totales": totales,
                                 "creado": datetime.now()}

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

        return jsonify({
            "ok": True,
            "id_sesion": id_sesion,
            "archivo_excel": nombre_excel,
            "totales": totales,
            "diagnosticos": diagnosticos,
            "limite_previa": LIMITE_PREVIA,
            "orden_tablas": orden,
            "tablas": tablas,
        })

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
