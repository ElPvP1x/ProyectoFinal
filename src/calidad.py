"""Puerta de calidad (Bronce -> Plata) con Pandera.

Valida esquema, tipos, rangos y unicidad. Los registros invalidos NO se borran:
van a cuarentena con el motivo documentado.
"""
import pandas as pd
import pandera.pandas as pa
from pandera.pandas import Check, Column, DataFrameSchema

# Rango plausible por serie (limites amplios: atrapan errores de captura, no movimientos reales).
RANGOS = {
    "tipo_cambio_fix_usd_mxn_diario": (5, 40),
    "tiie_28_dias_diaria": (0.5, 30),
    "valor_udis_diario": (3, 20),
    "inpc_general_mensual": (50, 300),
    "inpc_general_inegi_mensual": (50, 300),
}
FUENTES = ["banxico_sie", "inegi_bie"]
FECHA_MIN = pd.Timestamp("2010-01-01")


def _en_rango(df: pd.DataFrame) -> pd.Series:
    lo = df["serie"].map({k: v[0] for k, v in RANGOS.items()})
    hi = df["serie"].map({k: v[1] for k, v in RANGOS.items()})
    # NaN y serie desconocida los rechazan otros checks: aqui no se duplica el motivo
    return df["valor"].between(lo, hi) | lo.isna() | df["valor"].isna()


def esquema(hoy: pd.Timestamp) -> DataFrameSchema:
    return DataFrameSchema(
        {
            "fuente": Column(str, Check.isin(FUENTES, error="fuente_no_reconocida")),
            "serie": Column(str, Check.isin(list(RANGOS), error="serie_no_reconocida")),
            "fecha": Column(pa.DateTime, [Check.ge(FECHA_MIN, error="fecha_anterior_a_2010"),
                                          Check.le(hoy, error="fecha_futura")], nullable=False),
            "valor": Column(float, Check.gt(0, error="valor_no_positivo"), nullable=False),
            "fecha_texto": Column(str),
            "dato_texto": Column(str, nullable=True),
            "captura": Column(str),
        },
        checks=Check(_en_rango, name="valor_fuera_de_rango_por_serie"),
        unique=["serie", "fecha"],
        report_duplicates="exclude_first",
        strict=True,
        coerce=False,
    )


def compuerta(df: pd.DataFrame, hoy: pd.Timestamp | None = None):
    """Devuelve (validos, cuarentena). Todo registro cae en uno de los dos."""
    hoy = hoy or pd.Timestamp.today().normalize()
    df = df.reset_index(drop=True)
    try:
        esquema(hoy).validate(df, lazy=True)
        return df, df.iloc[0:0].assign(motivo=pd.Series(dtype=str))
    except pa.errors.SchemaErrors as e:
        fc = e.failure_cases
    estructurales = fc[fc["index"].isna()]
    if len(estructurales):  # columna ausente, tipo incorrecto, etc.: falla todo el lote
        raise ValueError("Esquema invalido (estructural):\n" + estructurales[["column", "check", "failure_case"]].to_string())
    # Los checks de DataFrame se reportan una vez por columna: dejar uno por (registro, check)
    fc = fc.drop_duplicates(["index", "check"]).copy()
    fc["index"] = fc["index"].astype(int)
    textos = df["dato_texto"].astype(str).to_dict()
    chk = fc["check"].astype(str)
    def _detalle(i, c, f):
        if c == "valor_fuera_de_rango_por_serie":
            return f"valor={textos[i]}"
        if c.endswith("uniqueness"):
            return "mismo (serie, fecha) ya existe en el lote"
        return str(f)
    fc["motivo"] = [f"{c} [{_detalle(i, c, f)}]" for i, c, f in zip(fc["index"], chk, fc["failure_case"])]
    motivos = fc.groupby("index")["motivo"].agg("; ".join)
    mal = df.index.isin(motivos.index)
    cuarentena = df[mal].assign(motivo=motivos.reindex(df.index[mal]).values)
    return df[~mal].reset_index(drop=True), cuarentena.reset_index(drop=True)
