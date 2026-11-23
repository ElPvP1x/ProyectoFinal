"""Pruebas de E2: linaje Bronce -> Oro y fuente geoespacial. Los lotes sinteticos son DE PRUEBA."""
import hashlib, json, sys, pathlib
import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

RAIZ = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
import geo, linaje  # noqa: E402


def _bronce_falso(tmp_path, contenido=b'{"bmx": {"series": [{"datos": []}]}}', registrar=True):
    d = tmp_path / "datos" / "bronce" / "banxico_sie" / "serie_x"
    d.mkdir(parents=True)
    ruta = d / "20260101T000000Z.json"
    ruta.write_bytes(contenido)
    if registrar:
        h = hashlib.sha256(contenido).hexdigest()
        (tmp_path / "datos" / "bronce" / "manifiesto.csv").write_text(
            f"20260101T000000Z,banxico_sie,serie_x,{ruta.name},{len(contenido)},{h}\n", encoding="utf-8")
    return ruta


def test_ficha_de_linaje(tmp_path):
    ruta = _bronce_falso(tmp_path)
    f = linaje.ficha_archivo(tmp_path, ruta)
    assert f["archivo_bronce"] == "datos/bronce/banxico_sie/serie_x/20260101T000000Z.json"
    assert f["fecha_ingesta"] == "2026-01-01T00:00:00Z"


def test_archivo_alterado_se_detecta(tmp_path):
    ruta = _bronce_falso(tmp_path)
    ruta.write_bytes(b'{"alterado": true}')
    with pytest.raises(ValueError, match="cambio"):
        linaje.ficha_archivo(tmp_path, ruta)


def test_archivo_sin_manifiesto_no_tiene_origen(tmp_path):
    ruta = _bronce_falso(tmp_path, registrar=False)
    with pytest.raises(ValueError, match="manifiesto"):
        linaje.ficha_archivo(tmp_path, ruta)


# --- Linaje sobre los datos reales del repositorio (el workflow corre el pipeline antes de las pruebas) ---
ORO = RAIZ / "datos" / "oro"
requiere_oro = pytest.mark.skipif(not (ORO / "linaje.csv").exists(), reason="correr src/pipeline.py primero")


@requiere_oro
def test_cada_registro_de_oro_es_rastreable():
    oro = pd.read_csv(ORO / "oro_mensual.csv", dtype={"mes": str})
    lin = pd.read_csv(ORO / "linaje.csv", dtype={"mes": str})
    assert oro["archivos_bronce"].notna().all() and oro["fecha_ingesta"].notna().all()
    assert set(oro["mes"]) <= set(lin["mes"])
    for archivo, h in lin[["archivo_bronce", "sha256_bronce"]].drop_duplicates().itertuples(index=False):
        assert linaje.sha256(RAIZ / archivo) == h, archivo


@requiere_oro
def test_rastrear_llega_al_texto_crudo():
    mes = pd.read_csv(ORO / "oro_mensual.csv", dtype={"mes": str})["mes"].iloc[-1]
    crudo = linaje.rastrear(mes, RAIZ)
    assert len(crudo) > 0 and crudo["dato_texto"].notna().all()


# --- Geoespacial ---
def _overpass_falso(tmp_path):
    elementos = [
        {"type": "node", "id": 1, "lat": 19.43, "lon": -99.13,
         "tags": {"office": "accountant", "name": "Despacho Pérez", "phone": "+52 55 0000 0000"}},
        {"type": "way", "id": 2, "center": {"lat": 20.67, "lon": -103.35}, "tags": {"amenity": "bank"}},
        {"type": "node", "id": 3, "lat": 40.0, "lon": -3.7, "tags": {"office": "accountant"}},  # Madrid
        {"type": "node", "id": 4, "lat": 19.0, "lon": -99.0, "tags": {"shop": "bakery"}},     # no aplica
        {"type": "node", "id": 1, "lat": 19.43, "lon": -99.13, "tags": {"office": "accountant"}},  # duplicado
    ]
    ruta = tmp_path / "ov.json"
    ruta.write_text(json.dumps({"elements": elementos}), encoding="utf-8")
    return ruta


def test_geo_descarta_datos_personales_y_manda_a_cuarentena(tmp_path):
    ficha = {"fuente": "osm_overpass", "serie": "x", "archivo_bronce": "a.json", "sha256_bronce": "h", "fecha_ingesta": "f"}
    validos, cuarentena = geo.leer_puntos(_overpass_falso(tmp_path), ficha)
    assert len(validos) + len(cuarentena) == 5
    assert set(validos["categoria"]) == {"despacho_contable", "banco"}
    for campo in ("name", "phone", "nombre", "telefono"):
        assert campo not in validos.columns
    motivos = " ".join(cuarentena["motivo"])
    for esperado in ("fuera_de_mexico", "categoria_no_reconocida", "duplicado"):
        assert esperado in motivos
    assert {"archivo_bronce", "sha256_bronce", "fecha_ingesta"} <= set(validos.columns)


def test_union_espacial_punto_en_poligono():
    entidades = gpd.GeoDataFrame({"entidad": ["Norte", "Sur"], "clave_iso": ["MX-N", "MX-S"]},
                                 geometry=[box(-100, 20, -98, 22), box(-100, 18, -98, 20)], crs="EPSG:4326")
    puntos = pd.DataFrame({"categoria": ["banco", "banco", "despacho_contable"],
                           "lon": [-99.0, -99.0, -98.99], "lat": [21.0, 19.0, 19.5]})
    r = geo.asignar_entidad(puntos, entidades)
    assert list(r["entidad"]) == ["Norte", "Sur", "Sur"]
    lin = {"archivo_bronce": "a", "sha256_bronce": "h", "fecha_ingesta": "2026-01-01T00:00:00Z"}
    res = geo.resumir(r, entidades, lin, lin).set_index("entidad")
    assert res.loc["Sur", "banco"] == 1 and res.loc["Sur", "despacho_contable"] == 1
    assert res["archivo_bronce_puntos"].notna().all()


# --- DENUE (segunda fuente geoespacial) ---
def _denue_falso(tmp_path):
    import zipfile
    import denue
    cols = ["id", "clee", "nom_estab", "raz_social", "codigo_act", "nombre_act", "per_ocu", "nom_vial", "numero_ext",
            "cve_ent", "entidad", "cve_mun", "municipio", "telefono", "correoelec", "www", "latitud", "longitud", "fecha_alta"]
    filas = [
        ["1", "x", "JUAN PEREZ CONTADOR", "", "541211", "Contabilidad", "0 a 5 personas", "HIDALGO", "10",
         "06", "Colima", "002", "Colima", "3120000000", "juan@correo.mx", "", "19.24", "-103.72", "2019-11"],
        ["2", "x", "DESPACHO SA", "DESPACHO SA DE CV", "541219", "Otros", "11 a 30 personas", "JUAREZ", "5",
         "06", "Colima", "002", "Colima", "", "", "", "19.25", "-103.73", "2020-01"],
        ["3", "x", "ABOGADOS", "", "541110", "Bufetes", "0 a 5 personas", "", "", "06", "Colima", "002", "Colima",
         "", "", "", "19.25", "-103.73", "2020-01"],                     # no es contabilidad: se filtra
        ["4", "x", "SIN COORDENADAS", "", "541211", "Contabilidad", "0 a 5 personas", "", "", "06", "Colima", "002",
         "Colima", "", "", "", "", "", "2020-01"],                       # va a cuarentena
    ]
    texto = ",".join(cols) + "\n" + "\n".join(",".join(f) for f in filas) + "\n"
    ruta = tmp_path / "denue.zip"
    with zipfile.ZipFile(ruta, "w") as z:
        z.writestr("conjunto_de_datos/denue_inegi_54_.csv", texto.encode("latin-1"))
    return denue, ruta


def test_denue_sin_datos_personales_y_con_cuarentena(tmp_path):
    denue, ruta = _denue_falso(tmp_path)
    ficha = {"fuente": "inegi_denue", "serie": "x", "archivo_bronce": "d.zip", "sha256_bronce": "h", "fecha_ingesta": "f"}
    validos, cuarentena = denue.leer(ruta, ficha)
    assert len(validos) == 2 and len(cuarentena) == 1          # el bufete de abogados no entra
    assert "sin_coordenadas" in cuarentena["motivo"].iloc[0]
    for campo in denue.PERSONALES:
        assert campo not in validos.columns and campo not in cuarentena.columns
    assert validos["de_11_o_mas"].tolist() == [False, True]
    assert {"archivo_bronce", "sha256_bronce", "fecha_ingesta"} <= set(validos.columns)


def test_denue_concordancia_de_entidad():
    import denue
    pts = pd.DataFrame({"cve_ent": ["06", "09", "15"], "clave_iso": ["MX-COL", "MX-CMX", "MX-JAL"]})
    assert denue.concordancia(pts) == pytest.approx(66.67)
