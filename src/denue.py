"""Segunda fuente geoespacial (E2): DENUE del INEGI, establecimientos de contabilidad.

OpenStreetMap sólo tiene 83 despachos contables en todo el país; el DENUE (directorio oficial
de unidades económicas) tiene miles. Se usa la descarga masiva del sector 54, que no pide token,
y se filtran las clases SCIAN 541211 (servicios de contabilidad y auditoría) y 541219 (otros
servicios relacionados con la contabilidad).

Bronce  inegi_denue/denue_sector54/<captura>.zip   (zip tal como lo publica el INEGI)
Plata   datos/plata/geo_denue_contables.csv        un renglón por establecimiento, SIN datos personales
Oro     columnas denue_* en datos/oro/geo_entidades.csv y datos/oro/geo_municipios.csv

Privacidad: muchos despachos son personas físicas cuyo nombre, teléfono, correo y domicilio
aparecen en el DENUE. Nada de eso pasa de Bronce: sólo se leen las columnas de CAMPOS.
"""
import io, pathlib, zipfile
import geopandas as gpd
import pandas as pd

ACTIVIDADES = {"541211": "contabilidad_y_auditoria", "541219": "otros_contabilidad"}
CAMPOS = ["id", "codigo_act", "per_ocu", "cve_ent", "entidad", "cve_mun", "municipio",
          "latitud", "longitud", "fecha_alta"]                     # lista blanca: nada más se lee
PERSONALES = ["nom_estab", "raz_social", "telefono", "correoelec", "www", "nom_vial", "numero_ext"]
GRANDES = ("11 a 30 personas", "31 a 50 personas", "51 a 100 personas", "101 a 250 personas", "251 y más personas")
CAJA_MX = (-118.6, 14.3, -86.5, 32.8)


def leer(ruta: pathlib.Path, ficha: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Devuelve (validos, cuarentena) con sólo las columnas no personales y el linaje."""
    z = zipfile.ZipFile(ruta)
    nombre = next(n for n in z.namelist() if n.startswith("conjunto_de_datos/") and n.endswith(".csv"))
    df = pd.read_csv(io.BytesIO(z.read(nombre)), encoding="latin-1", dtype=str, usecols=CAMPOS)
    df = df[df["codigo_act"].isin(ACTIVIDADES)].reset_index(drop=True)
    df = df.rename(columns={"entidad": "entidad_denue"})   # la union espacial agrega su propia "entidad"
    df["clase"] = df["codigo_act"].map(ACTIVIDADES)
    df["lat"] = pd.to_numeric(df.pop("latitud"), errors="coerce")
    df["lon"] = pd.to_numeric(df.pop("longitud"), errors="coerce")
    df["de_11_o_mas"] = df["per_ocu"].isin(GRANDES)
    motivo = pd.Series("", index=df.index)
    motivo[df["lat"].isna() | df["lon"].isna()] += "sin_coordenadas; "
    fuera = ~(df["lon"].between(CAJA_MX[0], CAJA_MX[2]) & df["lat"].between(CAJA_MX[1], CAJA_MX[3]))
    motivo[fuera & df["lon"].notna()] += "fuera_de_mexico; "
    motivo[df.duplicated("id")] += "duplicado; "
    df = df.assign(**{k: v for k, v in ficha.items() if k not in ("fuente", "serie")})
    mal = motivo.ne("")
    return df[~mal].reset_index(drop=True), df[mal].assign(motivo=motivo[mal].str.rstrip("; ")).reset_index(drop=True)


ISO = dict(zip([f"{i:02d}" for i in range(1, 33)],
               "AGU BCN BCS CAM COA COL CHP CHH CMX DUR GUA GRO HID JAL MEX MIC MOR NAY NLE OAX PUE QUE ROO SLP "
               "SIN SON TAB TAM TLA VER YUC ZAC".split()))


def concordancia(puntos: pd.DataFrame) -> float:
    """% de establecimientos cuya entidad declarada en el DENUE (cve_ent) coincide con la que da la union espacial."""
    declarada = "MX-" + puntos["cve_ent"].map(ISO)
    return round(float(100 * (declarada == puntos["clave_iso"]).mean()), 2) if len(puntos) else 0.0


def por_entidad(puntos: pd.DataFrame) -> pd.DataFrame:
    g = puntos.groupby("entidad_geo")
    return pd.DataFrame({"denue_contables": g.size(),
                         "denue_contables_11_o_mas": g["de_11_o_mas"].sum().astype(int)})


def por_municipio(puntos: pd.DataFrame, ficha: dict, lin_ent: dict) -> pd.DataFrame:
    g = puntos.groupby(["cve_ent", "entidad", "cve_mun", "municipio"])
    t = pd.DataFrame({"denue_contables": g.size(), "denue_contables_11_o_mas": g["de_11_o_mas"].sum().astype(int)}).reset_index()
    t["cve_geo"] = t["cve_ent"] + t["cve_mun"]   # clave del Marco Geoestadístico
    t["archivo_bronce"], t["sha256_bronce"], t["fecha_ingesta"] = ficha["archivo_bronce"], ficha["sha256_bronce"], ficha["fecha_ingesta"]
    return t.sort_values("denue_contables", ascending=False).reset_index(drop=True)


def mapa(ent: gpd.GeoDataFrame, ruta: pathlib.Path, fecha_denue: str):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    e = ent.to_crs("EPSG:6372")
    fig, axs = plt.subplots(1, 2, figsize=(15, 6.2))
    e.plot(column="denue_por_1000km2", cmap="Reds", scheme="Quantiles", k=5, legend=True, ax=axs[0],
           edgecolor="white", linewidth=0.6,
           legend_kwds={"title": "Despachos por 1,000 km²", "loc": "lower left", "fontsize": 8, "title_fontsize": 8,
                        "fmt": "{:.1f}", "frameon": False})
    axs[0].set_title("DENUE: establecimientos de contabilidad", fontsize=12, loc="left")
    e.plot(column="cobertura_osm_pct", cmap="Greys", scheme="UserDefined", vmin=-40,
           classification_kwds={"bins": [0.25, 0.5, 1, 100]}, legend=True, ax=axs[1], edgecolor="#9a9a9a", linewidth=0.5,
           legend_kwds={"title": "Despachos en OSM / DENUE (%)", "loc": "lower left", "fontsize": 8,
                        "title_fontsize": 8, "fmt": "{:.2f}", "frameon": False})
    axs[1].set_title("Cobertura de OpenStreetMap frente al DENUE", fontsize=12, loc="left")
    for ax in axs:
        ax.set_axis_off()
    total_d, total_o = int(ent["denue_contables"].sum()), int(ent["despacho_contable"].sum() + ent["asesor_fiscal"].sum())
    fig.text(0.01, 0.01, f"DENUE (INEGI, SCIAN 541211 y 541219): {total_d:,} establecimientos, captura {fecha_denue[:10]}. "
             f"OSM: {total_o} despachos y asesores fiscales. Fuentes: INEGI (Términos de Libre Uso), © colaboradores de "
             "OpenStreetMap (ODbL), geoBoundaries (CC BY 3.0 IGO).", fontsize=8, color="#555")
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(ruta, dpi=150, bbox_inches="tight")
    plt.close(fig)
