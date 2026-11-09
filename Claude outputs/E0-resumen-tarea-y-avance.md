# Entrega E0 — Observatorio Agro y Precios

Fecha límite: **lunes 9 de noviembre, 23:59 hrs** (tag `e0`).
Repositorio: https://github.com/ElPvP1x/ProyectoFinal
Carpeta local: `C:\Users\crist\Documents\GitHub\ProyectoFinal`
Equipo: 2 integrantes, Python. Sector elegido: agro y precios.

---

## 1. La tarea que se pidió

**Objetivo:** definir la pregunta central del observatorio, validarla con un actor real del sector, inicializar el repositorio en GitHub y dejar corriendo la máquina de captura en la capa Bronce.

**Entregables en el repo (tag `e0`):**

1. **Propuesta** (`docs/E0/propuesta.md`, 3 a 5 páginas):
   - Ficha del observatorio: sector, región, pregunta detonadora y cliente potencial.
   - Entrevista de campo (mínimo 15 min): 5 preguntas a alguien del sector y aprendizajes.
   - Las 3 preguntas analíticas: variable a pronosticar (E1), factores a experimentar (E2) y grupos multivariados a comparar (E3).
   - Plan de recopilación de datos: al menos 2 fuentes, con análisis ético y legal (robots.txt y términos de uso).
2. **Máquina de captura (capa Bronce):**
   - Extractor ético ejecutándose automáticamente con GitHub Actions.
   - Serie histórica inicial en datos crudos con al menos 36 periodos.
3. **Sistema de calidad (PSP):**
   - `calidad/tiempo-<nombre>.csv` y `calidad/defectos-<nombre>.csv` por integrante.
   - 3 objetivos de calidad medibles.
4. **Ficha de entrega técnica** (`docs/E0/ENTREGA.md`).

**Instrucciones de entrega:**

1. Crear el tag `e0` antes del lunes 9 de noviembre a las 23:59.
2. Agregar a los 3 profesores como colaboradores.
3. Registrar el enlace en el formulario oficial del proyecto integrador.
4. Marcar la tarea como entregada pegando el enlace del repo.

---

## 2. Lo que ya se avanzó

Se generó una estructura base de repositorio y se copiaron **11 de 12 archivos** a la carpeta local `ProyectoFinal`.

| Archivo | Qué contiene | Estado |
|---|---|---|
| `docs/E0/propuesta.md` | Borrador con ficha, 5 preguntas de entrevista, las 3 preguntas analíticas, plan de datos y tabla ética/legal | Copiado, **falta completar** |
| `docs/E0/ENTREGA.md` | Ficha técnica con tabla de entregables y 3 objetivos de calidad | Copiado, falta llenar campos |
| `src/extractor.py` | Extractor de Banxico SIE: guarda respuesta cruda con fecha y hash SHA-256, pausa de 2 s entre consultas, serie SP1 (INPC) desde 2010 | Copiado, **no probado con datos reales** |
| `config/fuentes.yml` | Lista de fuentes y series | Copiado, tiene 2 TODO |
| `requirements.txt`, `.gitignore`, `README.md` | Archivos de apoyo | Copiados |
| `calidad/tiempo-integrante1.csv`, `tiempo-integrante2.csv` | Registro de tiempos (vacíos, con encabezados) | Copiados, **renombrar** |
| `calidad/defectos-integrante1.csv`, `defectos-integrante2.csv` | Registro de defectos (vacíos, con encabezados) | Copiados, **renombrar** |
| `.github/workflows/captura.yml` | Workflow semanal de captura | **No se pudo copiar** (ruta protegida). Crear a mano, ver sección 4 |

**Objetivos de calidad propuestos:**

1. Cero ejecuciones fallidas del workflow en las últimas 4 corridas semanales.
2. Cada archivo crudo registrado en el manifiesto con su hash SHA-256 (100 %).
3. Máximo 1 defecto por cada 100 líneas de código.

**Limitaciones encontradas:**

- Desde el entorno de Claude no se pueden abrir los sitios de Banxico, INEGI, SIAP ni gob.mx. Por eso **no se descargó la serie histórica**, **no se verificaron los endpoints** y **no se revisaron robots.txt ni términos de uso**.
- No se pudo conectar Claude al repo de GitHub (error: acceso no habilitado en la sesión). Por eso **no se hizo push**.
- Claude no puede ejecutar `git` en la computadora del usuario, solo copiar archivos a la carpeta.

---

## 3. Lo que falta por hacer (en orden)

1. **Sacar el token gratis de la API de Banxico (SIE).**
2. **Hacer la entrevista** de al menos 15 minutos con alguien del sector y llenar la sección 2 de `propuesta.md`. No se puede inventar.
3. **Revisar robots.txt y términos de uso** de Banxico y de la segunda fuente, y llenar la tabla ética y legal.
4. **Completar `config/fuentes.yml`:** elegir la segunda fuente (INEGI BIE o SNIIM) y agregar una serie de alimentos o agro, para que el tema no sea solo INPC general.
5. **Definir producto y región** en la ficha de `propuesta.md` y reemplazar los `[CORCHETES]`.
6. **Renombrar** los CSV de calidad con los nombres reales de los integrantes.
7. **Crear a mano** `.github/workflows/captura.yml` (sección 4).
8. **Subir al repo** (sección 5).
9. En GitHub: crear el secreto `BANXICO_TOKEN`, agregar a los 3 profesores como colaboradores y correr el workflow `captura-bronce` a mano desde la pestaña Actions.
10. Confirmar que `datos/bronce/` tenga **36 o más periodos** y revisar `manifiesto.csv`.
11. Crear el tag y subirlo:
    ```
    git pull origin main
    git tag e0
    git push origin e0
    ```
12. Registrar el enlace en el formulario oficial y pegarlo en la tarea.

---

## 4. Contenido de `.github/workflows/captura.yml`

```yaml
name: captura-bronce
on:
  schedule:
    - cron: "0 14 * * 1"
  workflow_dispatch: {}
permissions:
  contents: write
jobs:
  capturar:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - run: pip install -r requirements.txt
      - run: python src/extractor.py
        env:
          BANXICO_TOKEN: ${{ secrets.BANXICO_TOKEN }}
      - name: Guardar capturas en el repo
        run: |
          git config user.name "bot-captura"
          git config user.email "bot@users.noreply.github.com"
          git add datos/
          git diff --cached --quiet || git commit -m "captura bronce $(date -u +%F)"
          git push
```

---

## 5. Cómo subir todo al repo

En una terminal dentro de `C:\Users\crist\Documents\GitHub\ProyectoFinal`:

```
git add -A
git commit -m "E0: estructura inicial"
git pull origin main --rebase
git push origin main
```

El remoto `origin` ya apunta a `https://github.com/ElPvP1x/ProyectoFinal.git` y la rama es `main`. Si prefieres SSH:
`git remote set-url origin git@github.com:ElPvP1x/ProyectoFinal.git`

Si GitHub pide contraseña, ya no acepta la normal: inicia sesión por el navegador cuando lo ofrezca o usa un token personal.

---

## 6. Para que Claude pueda subirlo por ti (opcional)

No se pudo conectar el repo a la sesión actual. Pasos probables, **sin comprobar**:

1. En github.com, Settings → Applications: instalar o revisar la app de Claude.
2. Darle acceso al repo `ProyectoFinal` con permiso de lectura y escritura.
3. Abrir una **tarea nueva** en la app de Claude (el acceso se aplica al iniciar).
4. Elegir el repo `ElPvP1x/ProyectoFinal` al iniciar.
5. Indicarle que los archivos de E0 ya están en la carpeta local y que cree el workflow, haga el push y el tag `e0`.

Dado el plazo, el push a mano suele ser más rápido.
