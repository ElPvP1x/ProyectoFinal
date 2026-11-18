"""Funciones de limpieza y preprocesamiento (capa Plata) y preparacion (capa Oro)."""
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import IsolationForest


# ---------- 1. Valores faltantes ----------
def reindexar_calendario(s: pd.Series, freq: str) -> pd.Series:
    """Pone la serie en su calendario esperado (B=habiles, D=diario, MS=mensual); lo ausente queda NaN."""
    return s.reindex(pd.date_range(s.index.min(), s.index.max(), freq=freq))


def diagnostico_faltantes(s: pd.Series) -> dict:
    """Pruebas sobre el patron de ausencia (s ya reindexada al calendario, con NaN en los huecos).

    MCAR: la ausencia no depende de nada. MAR: depende de algo observado (mes, nivel o volatilidad previos).
    MNAR: depende del propio valor ausente; no se puede probar con los datos, se argumenta con el origen.
    """
    falt = s.isna()
    res = {"n": int(len(s)), "faltantes": int(falt.sum()), "pct": round(100 * falt.mean(), 3)}
    if falt.sum() < 5:
        res.update(p_mes=None, p_nivel_previo=None, p_volatilidad_previa=None,
                   mecanismo="sin huecos suficientes para probar (practicamente completa)")
        return res
    mes = pd.crosstab(s.index.month, falt)
    res["p_mes"] = float(stats.chi2_contingency(mes)[1])
    ult = s.ffill()
    nivel = ult.shift(1)
    vol = np.log(ult).diff().abs().shift(1)
    res["p_nivel_previo"] = float(stats.mannwhitneyu(nivel[falt].dropna(), nivel[~falt].dropna()).pvalue)
    res["p_volatilidad_previa"] = float(stats.mannwhitneyu(vol[falt].dropna(), vol[~falt].dropna()).pvalue)
    dep = [k for k, p in (("mes", res["p_mes"]), ("nivel previo", res["p_nivel_previo"]),
                          ("volatilidad previa", res["p_volatilidad_previa"])) if p < 0.05]
    res["mecanismo"] = ("MAR (depende de: " + ", ".join(dep) + ")") if dep else "compatible con MCAR (sin dependencia detectada)"
    return res


def evaluar_imputacion(s: pd.Series, frac: float = 0.05, seed: int = 42) -> pd.DataFrame:
    """Oculta al azar una fraccion de valores conocidos, los imputa con cada metodo y mide el error (MAE)."""
    rng = np.random.default_rng(seed)
    conocidos = s.dropna().index
    oculto = rng.choice(conocidos, size=max(5, int(frac * len(conocidos))), replace=False)
    s2 = s.copy()
    s2[oculto] = np.nan
    metodos = {
        "ultimo_valor (ffill)": lambda x: x.ffill().bfill(),
        "interpolacion_lineal": lambda x: x.interpolate(method="time").bfill().ffill(),
        "media_global": lambda x: x.fillna(x.mean()),
    }
    filas = []
    for nombre, f in metodos.items():
        est = f(s2)[oculto]
        filas.append({"metodo": nombre, "MAE": float((est - s[oculto]).abs().mean()),
                      "RMSE": float(np.sqrt(((est - s[oculto]) ** 2).mean()))})
    return pd.DataFrame(filas).sort_values("MAE").reset_index(drop=True)


def imputar(s: pd.Series, metodo: str) -> pd.Series:
    if metodo.startswith("interpolacion"):
        return s.interpolate(method="time").bfill().ffill()
    if metodo.startswith("media"):
        return s.fillna(s.mean())
    return s.ffill().bfill()


# ---------- 2. Atipicos y ruido ----------
def marcar_atipicos(r: pd.Series, k: float = 1.5, z: float = 3.5, contaminacion: float = 0.01) -> pd.DataFrame:
    """Tres detectores sobre una serie de variaciones. Marca, no elimina.

    Series "escalonadas" (la TIIE casi no cambia dia a dia) tienen IQR y MAD iguales a 0; en ese caso los
    detectores se calibran solo con las variaciones distintas de cero, para no marcar cada cambio como atipico.
    """
    r = r.dropna()
    q1, q3 = r.quantile([0.25, 0.75])
    base = r[r != 0] if (q3 - q1 == 0 or stats.median_abs_deviation(r) == 0) else r
    q1, q3 = base.quantile([0.25, 0.75])
    iqr = q3 - q1
    inf, sup = q1 - k * iqr, q3 + k * iqr
    mad = stats.median_abs_deviation(base, scale="normal")
    zr = (r - base.median()) / mad if mad > 0 else pd.Series(0.0, index=r.index)
    iso = pd.Series(False, index=r.index)
    if len(base) > 10:
        iso.loc[base.index] = IsolationForest(contamination=contaminacion, random_state=0).fit_predict(
            base.to_numpy().reshape(-1, 1)) == -1
    out = pd.DataFrame({"atipico_iqr": (r < inf) | (r > sup), "z_robusto": zr,
                        "atipico_zrobusto": zr.abs() > z, "atipico_iforest": iso}, index=r.index)
    out["n_detectores"] = out[["atipico_iqr", "atipico_zrobusto", "atipico_iforest"]].sum(axis=1)
    out.attrs.update(limite_inf=float(inf), limite_sup=float(sup))
    return out


def winsorizar(r: pd.Series, inf: float, sup: float) -> pd.Series:
    return r.clip(lower=inf, upper=sup)


# ---------- 3. Normalizacion ----------
def minmax(s: pd.Series) -> pd.Series:
    rango = s.max() - s.min()
    return (s - s.min()) / rango if rango else s * 0.0


def zscore(s: pd.Series) -> pd.Series:
    sd = s.std(ddof=0)
    return (s - s.mean()) / sd if sd else s * 0.0


# ---------- 4. Discretizacion y jerarquias ----------
def jerarquia_temporal(fechas: pd.Series) -> pd.DataFrame:
    """Jerarquia conceptual: mes < trimestre < semestre < anio."""
    f = pd.to_datetime(fechas)
    return pd.DataFrame({"anio": f.dt.year, "semestre": f.dt.year.astype(str) + "-S" + ((f.dt.quarter + 1) // 2).astype(str),
                         "trimestre": f.dt.year.astype(str) + "-T" + f.dt.quarter.astype(str),
                         "mes": f.dt.strftime("%Y-%m")}, index=fechas.index)


def discretizar_cuantiles(s: pd.Series, etiquetas=("bajo", "medio", "alto")) -> pd.Series:
    return pd.qcut(s, q=len(etiquetas), labels=list(etiquetas))


def discretizar_umbrales(s: pd.Series, cortes, etiquetas) -> pd.Series:
    return pd.cut(s, bins=[-np.inf, *cortes, np.inf], labels=list(etiquetas))


# ---------- 5. Reduccion ----------
def seleccionar_variables(df: pd.DataFrame, protegidas, umbral: float = 0.95):
    """Seleccion por redundancia: quita variables con |r| > umbral frente a una ya conservada."""
    corr = df.corr().abs()
    conservadas = [c for c in protegidas if c in df.columns]
    descartadas = {}
    for c in df.columns:
        if c in conservadas:
            continue
        if df[c].var() == 0 or df[c].isna().all():
            descartadas[c] = "varianza cero"
            continue
        par = corr.loc[c, conservadas].sort_values(ascending=False) if conservadas else pd.Series(dtype=float)
        if len(par) and par.iloc[0] > umbral:
            descartadas[c] = f"|r|={par.iloc[0]:.3f} con {par.index[0]}"
        else:
            conservadas.append(c)
    return conservadas, descartadas
