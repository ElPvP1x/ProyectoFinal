"""Bronce -> Plata: lee la captura mas reciente de cada serie, pasa la puerta de calidad,
manda lo invalido a cuarentena y limpia lo valido (faltantes, atipicos)."""
import json, pathlib
import numpy as np
import pandas as pd
import calidad, limpieza

RAIZ = pathlib.Path(__file__).resolve().parents[1]
CALENDARIO = {  # frecuencia esperada de cada serie
    "tipo_cambio_fix_usd_mxn_diario": "B",   # dias habiles
    "tiie_28_dias_diaria": "B",
    "valor_udis_diario": "D",                # todos los dias
    "inpc_general_mensual": "MS",
    "inpc_general_inegi_mensual": "MS",
}


SERIES_TABULARES = ("banxico_sie", "inegi_bie")  # las geoespaciales tienen su propio flujo (geo.py)


def procedencia(raiz=RAIZ) -> pd.DataFrame:
    """Linaje de cada serie: que archivo de Bronce se uso, su hash y su fecha de ingesta.

    El hash se recalcula sobre el archivo y se compara con datos/bronce/manifiesto.csv:
    si no coincide, el archivo cambio despues de la captura y el pipeline se detiene.
    """
    import linaje
    filas = []
    for carpeta in sorted((raiz / "datos" / "bronce").glob("*/*")):
        if not carpeta.is_dir() or carpeta.parent.name not in SERIES_TABULARES:
            continue
        snaps = sorted(carpeta.glob("*.json"))
        if snaps:
            filas.append(linaje.ficha_archivo(raiz, snaps[-1]))
    cols = ["fuente", "serie", "archivo_bronce", "sha256_bronce", "fecha_ingesta"]
    return pd.DataFrame(filas, columns=cols)


def leer_bronce(raiz=RAIZ) -> pd.DataFrame:
    """Tabla larga con el TEXTO tal como llego mas campos parseados. Armoniza Banxico e INEGI."""
    partes = []
    for carpeta in sorted((raiz / "datos" / "bronce").glob("*/*")):
        if carpeta.parent.name not in SERIES_TABULARES:
            continue
        snaps = sorted(carpeta.glob("*.json")) if carpeta.is_dir() else []
        if not snaps:
            continue
        d = json.loads(snaps[-1].read_text(encoding="utf-8"))
        if "bmx" in d:      # Banxico: fecha dd/mm/aaaa, dato como texto
            obs = [(o.get("fecha"), o.get("dato")) for o in d["bmx"]["series"][0].get("datos", [])]
            fmt = "%d/%m/%Y"
        elif "Series" in d:  # INEGI: TIME_PERIOD aaaa/mm, OBS_VALUE como texto
            obs = [(o.get("TIME_PERIOD"), o.get("OBS_VALUE")) for o in d["Series"][0]["OBSERVATIONS"]]
            fmt = "%Y/%m"
        else:
            continue
        df = pd.DataFrame(obs, columns=["fecha_texto", "dato_texto"]).astype(str)
        df["fecha"] = pd.to_datetime(df["fecha_texto"], format=fmt, errors="coerce")
        df["valor"] = pd.to_numeric(df["dato_texto"].str.replace(",", "", regex=False), errors="coerce")
        df["fuente"], df["serie"], df["captura"] = carpeta.parent.name, carpeta.name, snaps[-1].stem
        partes.append(df)
    cols = ["fuente", "serie", "fecha", "valor", "fecha_texto", "dato_texto", "captura"]
    return pd.concat(partes, ignore_index=True)[cols] if partes else pd.DataFrame(columns=cols)


def limpiar_serie(df: pd.DataFrame, freq: str):
    s = df.set_index("fecha")["valor"].sort_index()
    s = limpieza.reindexar_calendario(s, freq)
    diag = limpieza.diagnostico_faltantes(s)
    ev = limpieza.evaluar_imputacion(s)
    mejor = ev.loc[0, "metodo"] if diag["faltantes"] else "no aplica"
    limpia = limpieza.imputar(s, mejor) if diag["faltantes"] else s
    var = np.log(limpia).diff()
    at = limpieza.marcar_atipicos(var)
    out = pd.DataFrame({"valor": s, "imputado": s.isna(), "valor_limpio": limpia, "variacion_log": var})
    out = out.join(at)
    out["variacion_winsor"] = limpieza.winsorizar(var, at.attrs["limite_inf"], at.attrs["limite_sup"])
    out.index.name = "fecha"
    info = {"faltantes": diag, "imputacion_evaluada": ev.round(5).to_dict("records"), "metodo_imputacion": mejor,
            "atipicos": {c: int(out[c].fillna(False).sum()) for c in
                         ["atipico_iqr", "atipico_zrobusto", "atipico_iforest"]}
                        | {"consenso_2_o_mas": int((out["n_detectores"] >= 2).sum())},
            "limites_iqr": [at.attrs["limite_inf"], at.attrs["limite_sup"]]}
    return out, info


def ejecutar(raiz=RAIZ, hoy=None) -> dict:
    bronce = leer_bronce(raiz)
    validos, cuarentena = calidad.compuerta(bronce, hoy)
    dq = raiz / "datos" / "cuarentena"
    dp = raiz / "datos" / "plata"
    dq.mkdir(parents=True, exist_ok=True)
    dp.mkdir(parents=True, exist_ok=True)
    cuarentena.to_csv(dq / "cuarentena.csv", index=False, encoding="utf-8")
    reporte = {"registros_bronce": int(len(bronce)), "validos": int(len(validos)), "cuarentena": int(len(cuarentena)),
               "pct_cuarentena": round(100 * len(cuarentena) / max(len(bronce), 1), 4),
               "motivos": cuarentena["motivo"].str.split(" [", regex=False).str[0].value_counts().to_dict() if len(cuarentena) else {},
               "series": {}}
    proc = procedencia(raiz).set_index("serie")
    for serie, df in validos.groupby("serie"):
        out, info = limpiar_serie(df, CALENDARIO[serie])
        # Linaje por registro: de donde salio cada fila de Plata
        p = proc.loc[serie]
        out["origen"] = np.where(out["imputado"], "imputado (interpolacion)", "bronce")
        out["fecha_ingesta"] = p["fecha_ingesta"]
        out["archivo_bronce"] = p["archivo_bronce"]
        out["sha256_bronce"] = p["sha256_bronce"]
        info["linaje"] = p.to_dict()
        out.to_csv(dp / f"{serie}.csv", encoding="utf-8")
        info["registros"] = int(len(df))
        reporte["series"][serie] = info
    (dp / "reporte.json").write_text(json.dumps(reporte, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return reporte
