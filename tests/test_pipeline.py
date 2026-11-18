"""Pruebas de la puerta de calidad y de la limpieza. Los registros defectuosos aqui son DE PRUEBA, inventados a proposito."""
import json, sys, pathlib
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
import calidad, limpieza, plata  # noqa: E402

BASE = dict(fuente="banxico_sie", serie="tipo_cambio_fix_usd_mxn_diario", captura="prueba")


def fila(fecha, valor, f_txt, d_txt, **kw):
    return {**BASE, **kw, "fecha": pd.Timestamp(fecha) if fecha else pd.NaT, "valor": valor,
            "fecha_texto": f_txt, "dato_texto": d_txt}


def lote_malo():
    return pd.DataFrame([
        fila("2020-01-02", 18.9, "02/01/2020", "18.9"),        # valido
        fila("2020-01-02", 19.0, "02/01/2020", "19.0"),        # duplicado (serie, fecha)
        fila(None, 18.9, "31/02/2020", "18.9"),                # fecha imposible
        fila("2020-01-03", np.nan, "03/01/2020", "N/E"),       # dato no numerico
        fila("2020-01-06", -1.0, "06/01/2020", "-1"),          # negativo
        fila("2020-01-07", 500.0, "07/01/2020", "500"),        # fuera de rango para un tipo de cambio
        fila("2999-01-01", 19.0, "01/01/2999", "19.0"),        # fecha futura
        fila("2020-01-08", 19.1, "08/01/2020", "19.1"),        # valido
    ])


def test_nada_se_pierde_en_silencio():
    entrada = lote_malo()
    validos, cuarentena = calidad.compuerta(entrada)
    assert len(validos) + len(cuarentena) == len(entrada)
    assert len(validos) == 2


def test_cada_registro_en_cuarentena_tiene_motivo():
    _, cuarentena = calidad.compuerta(lote_malo())
    assert cuarentena["motivo"].str.len().gt(0).all()
    motivos = " ".join(cuarentena["motivo"])
    for esperado in ("uniqueness", "not_nullable", "valor_no_positivo", "valor_fuera_de_rango_por_serie", "fecha_futura"):
        assert esperado in motivos


def test_lote_limpio_pasa_sin_cuarentena():
    validos, cuarentena = calidad.compuerta(lote_malo().iloc[[0, 7]])
    assert len(validos) == 2 and len(cuarentena) == 0


def test_esquema_estructural_roto_falla_todo_el_lote():
    with pytest.raises(ValueError):
        calidad.compuerta(lote_malo().drop(columns=["valor"]))


def test_inegi_se_armoniza_con_banxico(tmp_path):
    d = tmp_path / "datos" / "bronce" / "inegi_bie" / "inpc_general_inegi_mensual"
    d.mkdir(parents=True)
    obs = [{"TIME_PERIOD": "2020/01", "OBS_VALUE": "105.934"}, {"TIME_PERIOD": "2020/02", "OBS_VALUE": "106.2"}]
    (d / "20260101T000000Z.json").write_text(json.dumps({"Series": [{"OBSERVATIONS": obs}]}), encoding="utf-8")
    df = plata.leer_bronce(tmp_path)
    assert list(df["fecha"]) == [pd.Timestamp("2020-01-01"), pd.Timestamp("2020-02-01")]
    assert df["valor"].dtype == float


def test_imputacion_y_diagnostico():
    idx = pd.bdate_range("2020-01-01", periods=300)
    s = pd.Series(np.linspace(18, 22, 300), index=idx)
    s.iloc[[10, 50, 51, 120, 200]] = np.nan
    assert limpieza.diagnostico_faltantes(s)["faltantes"] == 5
    ev = limpieza.evaluar_imputacion(s)
    assert ev.loc[0, "metodo"] != "media_global"            # en una tendencia, la media global es peor
    assert not limpieza.imputar(s, ev.loc[0, "metodo"]).isna().any()


def test_atipicos_detecta_un_salto_extremo():
    rng = np.random.default_rng(0)
    r = pd.Series(rng.normal(0, 0.003, 500))
    r.iloc[250] = 0.2
    at = limpieza.marcar_atipicos(r)
    assert at.loc[250, "n_detectores"] == 3


def test_normalizacion_y_discretizacion():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    assert limpieza.minmax(s).min() == 0 and limpieza.minmax(s).max() == 1
    assert abs(limpieza.zscore(s).mean()) < 1e-12 and abs(limpieza.zscore(s).std(ddof=0) - 1) < 1e-12
    assert set(limpieza.discretizar_cuantiles(s)) == {"bajo", "medio", "alto"}


def test_seleccion_quita_redundantes():
    x = pd.Series(np.arange(50, dtype=float))
    df = pd.DataFrame({"a": x, "b": x * 2 + 1, "c": np.random.default_rng(1).normal(size=50)})
    conservadas, descartadas = limpieza.seleccionar_variables(df, ["a"])
    assert "b" in descartadas and "c" in conservadas
