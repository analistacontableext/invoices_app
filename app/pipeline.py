"""
Puente entre la app de revisión y el motor de parsing de script.py.

No se duplica lógica de negocio: se reutilizan tal cual generar_nombre(),
parse_document(), es_factura_valida(), calcular_conversion_pen(),
calcular_due_days() y las funciones de Google Sheets ya definidas en script.py.

Un mismo PO puede traer varios documentos (varias facturas o una factura
partida en varios PDFs), así que se procesan como un lote: cada archivo se
parsea por separado con su propio nombre estandarizado, pero todas las líneas
resultantes se combinan en una sola tabla de revisión.
"""
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import re
import uuid

import pandas as pd

import script
import storage

PO_PATTERN = re.compile(r"^IMP\d+(?:-\d+)?-\d{4}$")
_PO_AL_INICIO_DEL_NOMBRE = re.compile(r"^IMP(\d+)((?:-\d+)?)-(\d{4})")

COLUMNAS_ID = ("marca", "po", "invoice", "periodo", "item", "codigo_producto")


class POInvalidoError(Exception):
    pass


@dataclass
class ArchivoProcesado:
    filename_original: str
    nombre_final: str
    staged_path: Path
    po: str


@dataclass
class ResultadoProcesado:
    marca: str
    proveedor: str
    pos: list[str]
    archivos: list[ArchivoProcesado]
    df: pd.DataFrame
    advertencias: list[str] = field(default_factory=list)
    ajustes: pd.DataFrame = field(default_factory=pd.DataFrame)


@dataclass
class ResultadoIngesta:
    insertados: int
    duplicados: int
    worked_paths: list[storage.DriveFile]
    ajustes_insertados: int = 0
    ajustes_duplicados: int = 0


CATEGORIAS_AJUSTE = ("DESCUENTO", "CREDITO", "CARGO", "CUSTOM")
COLUMNAS_AJUSTE = (
    "id", "marca", "proveedor", "po", "invoice", "invoice_date", "periodo",
    "categoria", "descripcion", "monto", "origen", "nombre_archivo",
)


def validar_po(po: str) -> str:
    po_limpio = (po or "").strip().upper()
    if not PO_PATTERN.match(po_limpio):
        raise POInvalidoError(
            f"'{po}' no tiene el formato esperado (ej. IMP154-2025 o IMP012-2-2025)"
        )
    return po_limpio


def detectar_po_desde_nombre(filename: str) -> str | None:
    """Busca un PO al inicio del nombre del archivo (ej. 'IMP014-2026_INVOICE...pdf'),
    para no tener que tipearlo a mano cuando ya viene en el nombre. El número
    principal se rellena a 3 dígitos (IMP94 -> IMP094) porque esa es la
    convención vigente, aunque algunos archivos viejos no la sigan."""
    m = _PO_AL_INICIO_DEL_NOMBRE.match(filename.strip())
    if not m:
        return None
    numero, sub, anio = m.groups()
    return f"IMP{int(numero):03d}{sub}-{anio}".upper()


def procesar_documentos(marca: str, archivos: list[tuple[str, bytes, str]]) -> ResultadoProcesado:
    """
    archivos: lista de (filename, content, po) — cada archivo trae su propio PO
    ya confirmado. Pueden ser todos el mismo PO (varias facturas de un mismo
    PO, o una factura partida en varios PDFs) o un lote mixto con PO distinto
    por archivo (ej. rescatando muchas facturas viejas de golpe).
    """
    proveedor = script.MARCAS[marca]["proveedor"]
    advertencias = []
    archivos_procesados: list[ArchivoProcesado] = []
    nombres_usados: set[str] = set()
    todos_los_registros = []
    todos_los_ajustes = []
    pos_usados: set[str] = set()
    ids_vistos_en_lote: set[str] = set()

    for filename, content, po_bruto in archivos:
        try:
            po = validar_po(po_bruto)
        except POInvalidoError as e:
            advertencias.append(f"'{filename}': {e} — se omitió este archivo del lote.")
            continue
        pos_usados.add(po)

        staged_raw = storage.stage_uploaded_file(po, filename, content)

        es_excel = staged_raw.suffix.lower() == ".xlsx"
        if not es_excel:
            es_valida, razon = script.es_factura_valida(staged_raw, verbose=False)
            if not es_valida:
                advertencias.append(
                    f"'{filename}' no parece una factura válida ({razon}). "
                    "Revisa/completa esos datos manualmente en la tabla antes de confirmar."
                )

        nombre_final = script.generar_nombre(staged_raw, marca, proveedor)
        if not nombre_final:
            advertencias.append(
                f"No se pudo generar el nombre estandarizado para '{filename}' "
                "(revisa que el PO y la marca sean correctos). Se usó un nombre de respaldo."
            )
            nombre_final = f"{po}_{filename}"

        nombre_final = _nombre_unico_en_lote(nombre_final, nombres_usados)
        staged_final = storage.rename_in_staging(staged_raw, nombre_final)

        registros = script.parse_document(staged_final, marca, proveedor)

        # Duplicado exacto de otro archivo YA procesado en este mismo lote
        # (mismos ids: misma factura, mismo PO, mismas líneas) — se descarta
        # de una vez para que solo una de las dos copias termine en 'worked'.
        # Esto es habitual con facturas viejas que se guardaron dos veces con
        # nombres de archivo distintos.
        ids_del_archivo = {r["id"] for r in registros if r.get("id")}
        if ids_del_archivo and ids_del_archivo.issubset(ids_vistos_en_lote):
            advertencias.append(
                f"'{filename}' es un duplicado exacto de otro archivo ya procesado en este lote "
                f"(misma factura, mismo PO) — se descartó automáticamente y no se subirá a worked."
            )
            storage.discard_staged_file(staged_final)
            continue
        ids_vistos_en_lote |= ids_del_archivo
        nombres_usados.add(nombre_final)

        archivos_procesados.append(
            ArchivoProcesado(filename_original=filename, nombre_final=nombre_final, staged_path=staged_final, po=po)
        )

        # Ajustes (descuento/crédito/cargo) detectados automáticamente — solo
        # sugerencias, se muestran en la app para verificar/editar/borrar
        # antes de guardarse, igual que las líneas de producto.
        if registros:
            df_excel_para_ajustes = pd.read_excel(staged_final, header=None) if es_excel else None
            candidatos = script.detectar_ajustes(staged_final, marca, df_excel=df_excel_para_ajustes)
            primero = registros[0]
            for descripcion, monto, categoria in candidatos:
                todos_los_ajustes.append({
                    "id": f"{marca}_{po}_{primero.get('invoice', '')}_{categoria}",
                    "marca": marca,
                    "proveedor": proveedor,
                    "po": po,
                    "invoice": primero.get("invoice", ""),
                    "invoice_date": primero.get("invoice_date", ""),
                    "periodo": primero.get("periodo", ""),
                    "categoria": categoria,
                    "descripcion": descripcion,
                    "monto": monto,
                    "origen": "AUTO",
                    "nombre_archivo": nombre_final,
                })

        if not registros:
            marca_sugerida = _detectar_marca_alternativa(staged_final, marca)
            if marca_sugerida:
                advertencias.append(
                    f"'{filename}' no generó líneas con la marca seleccionada ('{marca}'), "
                    f"pero sí se reconoce como factura de **{marca_sugerida}**. "
                    "Verifica que elegiste la marca/proveedor correcto."
                )
            else:
                advertencias.append(
                    f"No se pudieron extraer líneas automáticamente de '{filename}'. "
                    "Se agregó una fila vacía para que la completes manualmente."
                )
            registros = [_fila_vacia(marca, proveedor, po, nombre_final)]

        todos_los_registros.extend(registros)

    df = pd.DataFrame(todos_los_registros)
    df = df.drop_duplicates(subset=["id"]) if "id" in df.columns else df

    for col in df.columns:
        if col == "total_factura_pdf":
            # NaN acá significa "el parser no extrae el total declarado en
            # el PDF" (la mayoría, todavía) — no "el total es 0". Rellenar
            # con 0 haría que el resumen por factura marque como
            # discrepancia cada factura de esas marcas, así que se deja
            # tal cual para que _resumen_por_factura() lo trate como
            # "no disponible" y no compare.
            continue
        if df[col].dtype.kind in "fi":
            df[col] = df[col].fillna(0)
        else:
            df[col] = df[col].fillna("")

    df["fecha_carga"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    df = script.calcular_conversion_pen(df)
    df = script.calcular_due_days(df)

    ids_existentes = _ids_existentes_seguro()
    df["ya_en_sheet"] = df["id"].isin(ids_existentes) if "id" in df.columns else False
    if df["ya_en_sheet"].any():
        advertencias.append(
            "Algunas filas ya existen en Google Sheets (columna 'ya_en_sheet'). "
            "Si confirmas, esas filas se omitirán para no duplicar."
        )

    df_ajustes = pd.DataFrame(todos_los_ajustes, columns=list(COLUMNAS_AJUSTE))

    return ResultadoProcesado(
        marca=marca,
        proveedor=proveedor,
        pos=sorted(pos_usados),
        archivos=archivos_procesados,
        df=df,
        advertencias=advertencias,
        ajustes=df_ajustes,
    )


def confirmar_e_ingestar(
    resultado: ResultadoProcesado,
    df_editado: pd.DataFrame,
    archivos_excluidos: set[str] | None = None,
    df_ajustes_editado: pd.DataFrame | None = None,
) -> ResultadoIngesta:
    """
    archivos_excluidos: nombres_final de archivos del lote que se quieren dejar
    fuera de esta subida (ej. porque el parser no los leyó bien). Sus líneas no
    se insertan en Sheets y el archivo no se mueve a 'worked' — se descarta el
    temporal de staging, pero el PDF original del usuario no se toca en ningún
    lado, así que puede volver a subirlo más adelante cuando se arregle el parser.

    df_ajustes_editado: descuentos/créditos/cargos detectados (o agregados a
    mano) que el usuario ya verificó en la app — se suben a la pestaña
    'ajustes' del mismo spreadsheet, separado de las líneas de producto.
    """
    archivos_excluidos = archivos_excluidos or set()

    df_final = df_editado.drop(columns=["ya_en_sheet"], errors="ignore").copy()
    if archivos_excluidos and "nombre_archivo" in df_final.columns:
        df_final = df_final[~df_final["nombre_archivo"].isin(archivos_excluidos)]
    df_final = _asegurar_ids(df_final)

    sheet = script.conectar_google_sheets()
    if sheet is None:
        raise RuntimeError("No se pudo conectar a Google Sheets (revisa credenciales.json)")

    ids_existentes = script.obtener_ids_existentes(sheet)
    registros = df_final.to_dict("records")
    insertados, duplicados = script.insertar_en_sheet_incremental(sheet, registros, ids_existentes)

    worked_paths = []
    for archivo in resultado.archivos:
        if archivo.nombre_final in archivos_excluidos:
            storage.discard_staged_file(archivo.staged_path)
        else:
            worked_paths.append(storage.move_to_worked(resultado.marca, archivo.staged_path, archivo.nombre_final))

    ajustes_insertados = 0
    ajustes_duplicados = 0
    if df_ajustes_editado is not None and not df_ajustes_editado.empty:
        df_ajustes_final = df_ajustes_editado.copy()
        if archivos_excluidos and "nombre_archivo" in df_ajustes_final.columns:
            df_ajustes_final = df_ajustes_final[~df_ajustes_final["nombre_archivo"].isin(archivos_excluidos)]
        # Descarta filas nuevas que el usuario dejó a medio llenar (sin monto
        # numérico) — de otro modo se subiría "nan" como texto al Sheet.
        montos_numericos = pd.to_numeric(df_ajustes_final["monto"], errors="coerce")
        df_ajustes_final = df_ajustes_final[montos_numericos.notna()]
        df_ajustes_final = _asegurar_ids_ajustes(df_ajustes_final)
        df_ajustes_final["fecha_carga"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if not df_ajustes_final.empty:
            hoja_ajustes = script.conectar_hoja_ajustes()
            if hoja_ajustes is None:
                raise RuntimeError("No se pudo conectar a la pestaña 'ajustes' (revisa credenciales.json)")
            ids_existentes_ajustes = script.obtener_ids_existentes_ajustes(hoja_ajustes)
            ajustes_insertados, ajustes_duplicados = script.insertar_ajustes_en_sheet(
                hoja_ajustes, df_ajustes_final.to_dict("records"), ids_existentes_ajustes
            )

    return ResultadoIngesta(
        insertados=insertados,
        duplicados=duplicados,
        worked_paths=worked_paths,
        ajustes_insertados=ajustes_insertados,
        ajustes_duplicados=ajustes_duplicados,
    )


def meses_con_tc_faltante(df: pd.DataFrame) -> list[str]:
    """Periodos (YYYYMM) donde alguna línea en USD/EUR se quedó sin tipo de
    cambio ('tc' vacío) — indica que falta el PDF de SUNAT de ese mes en
    SUNAT_DIR. La app usa esto para pedirle al usuario que lo suba."""
    if df.empty or "tc" not in df.columns or "moneda" not in df.columns:
        return []
    necesita_tc = df["moneda"].isin(["USD", "EUR"])
    falta = necesita_tc & df["tc"].isna()
    if not falta.any():
        return []
    return sorted(df.loc[falta, "periodo"].dropna().astype(str).unique().tolist())


def recalcular_conversion_pen(df: pd.DataFrame) -> pd.DataFrame:
    """Vuelve a calcular tc/costo_unitario_pen/importe_pen — se llama
    después de que el usuario sube el PDF de SUNAT que faltaba, para
    completar las filas que se habían quedado sin conversión.
    calcular_conversion_pen() cachea en memoria lo que ya leyó antes (ver
    script._cargar_usd_pen_dict), así que llamarla de nuevo es barata: solo
    lee el PDF recién subido, no vuelve a escanear todo SUNAT_DIR."""
    return script.calcular_conversion_pen(df)


def descartar(resultado: ResultadoProcesado) -> None:
    for archivo in resultado.archivos:
        storage.discard_staged_file(archivo.staged_path)


def _nombre_unico_en_lote(nombre_final: str, usados: set[str]) -> str:
    """Evita que dos archivos del mismo lote generen el mismo nombre estandarizado
    (ej. dos PDFs de la misma factura) y se pisen entre sí en staging/worked."""
    if nombre_final not in usados:
        return nombre_final
    base = Path(nombre_final)
    contador = 2
    while f"{base.stem}_{contador}{base.suffix}" in usados:
        contador += 1
    return f"{base.stem}_{contador}{base.suffix}"


def _detectar_marca_alternativa(staged_path: Path, marca_actual: str) -> str | None:
    """Si el parser de la marca seleccionada no extrajo nada, prueba con los
    parsers de las demás marcas (son solo texto + regex, rápidos) para sugerir
    cuál podría ser la correcta. Heurística barata, sin LLM: si algún otro
    parser sí devuelve líneas, es una señal fuerte de que se eligió la marca
    equivocada."""
    for otra_marca, config in script.MARCAS.items():
        if otra_marca == marca_actual:
            continue
        try:
            registros = script.parse_document(staged_path, otra_marca, config["proveedor"])
        except Exception:
            continue
        if registros:
            return otra_marca
    return None


def _asegurar_ids(df: pd.DataFrame) -> pd.DataFrame:
    """Genera un 'id' para filas agregadas/editadas manualmente que quedaron sin
    id: insertar_en_sheet_incremental descarta silenciosamente cualquier fila
    con id vacío, así que sin esto se perdería la fila sin avisar."""
    df = df.copy()
    if "id" not in df.columns:
        df["id"] = ""

    faltantes = df["id"].astype(str).str.strip() == ""
    for idx in df[faltantes].index:
        partes = [
            str(df.at[idx, c]).strip()
            for c in COLUMNAS_ID
            if c in df.columns and str(df.at[idx, c]).strip()
        ]
        df.at[idx, "id"] = "_".join(partes) if partes else f"MANUAL_{uuid.uuid4().hex[:8]}"

    return df


def _asegurar_ids_ajustes(df: pd.DataFrame) -> pd.DataFrame:
    """Igual que _asegurar_ids() pero para la tabla de ajustes: genera un id
    para las filas que el usuario agregó a mano en la app (categoría + po +
    invoice + descripción alcanza para que sea estable si se vuelve a subir
    el mismo archivo)."""
    df = df.copy()
    if "id" not in df.columns:
        df["id"] = ""

    faltantes = df["id"].astype(str).str.strip() == ""
    columnas_id = ("marca", "po", "invoice", "categoria", "descripcion")
    for idx in df[faltantes].index:
        partes = [
            str(df.at[idx, c]).strip()
            for c in columnas_id
            if c in df.columns and str(df.at[idx, c]).strip()
        ]
        df.at[idx, "id"] = "_".join(partes) if partes else f"AJUSTE_MANUAL_{uuid.uuid4().hex[:8]}"

    return df


def _ids_existentes_seguro() -> set:
    try:
        sheet = script.conectar_google_sheets()
        return script.obtener_ids_existentes(sheet)
    except Exception:
        return set()


def _fila_vacia(marca: str, proveedor: str, po: str, nombre_archivo: str) -> dict:
    return {
        "id": "", "marca": marca, "proveedor": proveedor, "invoice": "",
        "invoice_date": "", "due_date": "", "po": po, "incoterm": "",
        "periodo": "", "item": "", "codigo_producto": "", "tipo_codigo": "",
        "descripcion": "", "cantidad": 0, "costo_unitario": 0, "moneda": "",
        "importe": 0, "sample": "", "nombre_archivo": nombre_archivo,
    }
