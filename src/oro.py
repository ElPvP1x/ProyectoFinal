"""Plata -> Oro: integra las fuentes en una tabla mensual, normaliza, discretiza y reduce."""
import json, pathlib
import pandas as pd
import limpieza

RAIZ = pathlib.Path(__file__).resolve().parents[1]
PROTEGIDAS = ["fix_prom", "tiie_prom", "inpc", "inflacion_anual"]  # variables que E1/E2/E3 necesitan


def _leer(raiz, serie):
    ruta = raiz / "datos" / "plata" / f"{serie}.csv"
    return pd.read_csv(ruta, index_col="fecha", parse_dates=True) if ruta.exists() else None


def integrar(raiz=RAIZ) -> pd.DataFrame:
    """Fusion heterogenea: diaria (FIX, TIIE, UDIS) y mensual (INPC) a una sola rejilla mensual."""
    m = {}
    for nombre, serie in [("fix", "tipo_cambio_fix_usd_mxn_diario"), ("tiie", "tiie_28_dias_diaria"),
                          ("udis", "valor_udis_diario")]:
        d = _leer(raiz, serie)
        if d is None:
            continue
        g = d["valor_limpio"].groupby(d.index.to_period("M"))
        m[f"{nombre}_prom"], m[f"{nombre}_cierre"] = g.mean(), g.last()
        if nombre == "fix":
            m["fix_std"] = g.std()
            m["fix_dias_imputados"] = d["imputado"].groupby(d.index.to_period("M")).sum()
    for nombre, serie in [("inpc", "inpc_general_mensual"), ("inpc_inegi", "inpc_general_inegi_mensual")]:
        d = _leer(raiz, serie)
        if d is not None:
            m[nombre] = pd.Series(d["valor_limpio"].to_numpy(), index=d.index.to_period("M"))
    df = pd.DataFrame(m).sort_index()
    df.index.name = "mes"
    df["fix_var_mensual"] = df["fix_prom"].pct_change() * 100
    df["inflacion_anual"] = df["inpc"].pct_change(12) * 100
    df["tasa_real"] = df["tiie_prom"] - df["inflacion_anual"]
    if "inpc_inegi" in df:  # discrepancia entre fuentes del mismo indicador
        df["dif_inpc_banxico_inegi"] = df["inpc"] - df["inpc_inegi"]
    df["mes_completo"] = df[["fix_prom", "tiie_prom", "inpc", "inflacion_anual"]].notna().all(axis=1)
    return df


def ejecutar(raiz=RAIZ) -> dict:
    df = integrar(raiz)
    do = raiz / "datos" / "oro"
    do.mkdir(parents=True, exist_ok=True)
    tabla = df.copy()
    tabla.index = tabla.index.astype(str)
    tabla.to_csv(do / "integrado_mensual.csv", encoding="utf-8")
    comp = df[df["mes_completo"]].copy()
    excluidas = ("mes_completo", "fix_dias_imputados", "dif_inpc_banxico_inegi", "inpc_inegi")
    candidatas = [c for c in comp.columns if c not in excluidas]
    elegidas, descartadas = limpieza.seleccionar_variables(comp[candidatas].dropna(), PROTEGIDAS)
    oro = comp[elegidas].copy()
    params = {}
    for c in elegidas:   # normalizacion: Min-Max y Z-Score
        oro[f"{c}_mm"], oro[f"{c}_z"] = limpieza.minmax(oro[c]), limpieza.zscore(oro[c])
        params[c] = {"min": float(oro[c].min()), "max": float(oro[c].max()),
                     "media": float(oro[c].mean()), "desv": float(oro[c].std(ddof=0))}
    oro["fix_nivel"] = limpieza.discretizar_cuantiles(oro["fix_prom"])
    oro["tiie_nivel"] = limpieza.discretizar_umbrales(oro["tiie_prom"], [5, 8], ["baja", "media", "alta"])
    oro["inflacion_nivel"] = limpieza.discretizar_umbrales(oro["inflacion_anual"], [2, 4, 6],
                                                           ["<2%", "2-4% (meta Banxico)", "4-6%", ">6%"])
    fechas = pd.Series(oro.index.to_timestamp(), index=oro.index)
    oro = pd.concat([limpieza.jerarquia_temporal(fechas).drop(columns="mes"), oro], axis=1)
    oro.index = oro.index.astype(str)
    oro.index.name = "mes"
    oro.to_csv(do / "oro_mensual.csv", encoding="utf-8")
    rep = {"meses_integrados": int(len(df)), "meses_completos": int(len(comp)),
           "meses_parciales": [str(i) for i in df.index[~df["mes_completo"]]],
           "variables_candidatas": candidatas, "variables_conservadas": elegidas, "variables_descartadas": descartadas,
           "parametros_normalizacion": params,
           "cortes_fix_terciles": [float(x) for x in oro["fix_prom"].quantile([1 / 3, 2 / 3])]}
    (do / "reporte.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    return rep
