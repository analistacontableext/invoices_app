"""
Capa de almacenamiento para la app de revisión de facturas.

El staging (archivo recién subido, todavía sin confirmar) sigue siendo
filesystem local efímero (tempfile) — eso es intencional, no depende de
Drive en ningún entorno. La persistencia final (mover a 'worked', guardar un
PDF de SUNAT) sí es Google Drive API, vía app/drive_client.py.

Nota (histórica, 2026-07-08): se había intentado subir por Drive API con la
cuenta de servicio, pero las cuentas de servicio no tienen cuota de
almacenamiento propia en "Mi unidad" — Google devuelve 403
storageQuotaExceeded aunque la carpeta esté compartida con ellas (solo
funcionan así en Shared Drives reales). Resuelto (2026-07-15): cada usuario
sube con su propia cuenta OAuth (ver app/auth.py + app/drive_client.py), así
la subida usa el permiso/cuota de la persona que inició sesión, no la cuenta
de servicio — funciona igual en una carpeta personal compartida o en una
Shared Drive real, sin depender de cuál sea.
"""
from dataclasses import dataclass
from pathlib import Path
import mimetypes
import tempfile
import uuid

import script
import drive_client


@dataclass(frozen=True)
class DriveFile:
    """Resultado de guardar algo en Drive — reemplaza el Path local que
    devolvían estas funciones antes de la migración. __str__ devuelve el
    nombre de archivo para que cualquier mensaje de éxito que hacía
    str(resultado) siga funcionando sin cambios."""
    id: str
    name: str
    web_view_link: str = ""

    def __str__(self) -> str:
        return self.name


def staging_dir() -> Path:
    """Carpeta temporal donde se guardan los archivos subidos mientras se revisan
    (todavía no confirmados, no forman parte de 'raw' ni de 'worked')."""
    d = Path(tempfile.gettempdir()) / "revisor_facturas_staging"
    d.mkdir(parents=True, exist_ok=True)
    return d


def stage_uploaded_file(po: str, filename: str, content: bytes) -> Path:
    """
    Guarda el archivo subido con el PO como prefijo del nombre, imitando la
    convención que hoy se aplica manualmente a los archivos en 'raw'
    (IMP###-YYYY_...), para que generar_nombre() y los parsers de script.py
    lo reconozcan sin modificaciones.
    """
    nombre_con_po = f"{po}_{filename}"
    destino = staging_dir() / nombre_con_po
    destino.write_bytes(content)
    return destino


def rename_in_staging(staged_path: Path, nombre_final: str) -> Path:
    """Renombra el archivo en staging al nombre estandarizado que generar_nombre()
    calculó, igual que hace procesar() al mover de 'raw' a 'worked'."""
    destino = staging_dir() / nombre_final
    if destino.exists() and destino != staged_path:
        destino.unlink()
    if staged_path != destino:
        staged_path.rename(destino)
    return destino


def move_to_worked(marca: str, staged_path: Path, nombre_final: str) -> DriveFile:
    """Sube el archivo confirmado a la carpeta 'worked' de la marca en Drive
    (usando la cuota del usuario logueado, ver módulo drive_client) y borra
    el temporal de staging — ya no queda ninguna copia local."""
    folder_id = script.MARCAS[marca]["worked_folder_id"]
    content = staged_path.read_bytes()
    mimetype = mimetypes.guess_type(nombre_final)[0] or "application/octet-stream"
    resultado = drive_client.upload_or_replace(folder_id, nombre_final, content, mimetype)
    staged_path.unlink(missing_ok=True)
    return DriveFile(id=resultado["id"], name=resultado["name"], web_view_link=resultado.get("webViewLink", ""))


def discard_staged_file(staged_path: Path) -> None:
    """Elimina un archivo en staging que el usuario decidió no subir."""
    if staged_path.exists():
        staged_path.unlink()


def guardar_pdf_sunat(content: bytes, periodo: str) -> DriveFile:
    """Guarda un PDF de tipo de cambio de SUNAT subido desde la app: lo sube
    a la carpeta de Drive (SUNAT_TC_FOLDER_ID) y además lo escribe en el
    espejo local que script.SUNAT_DIR apunte en este momento (en dev local
    es la carpeta real; en modo nube es el directorio temporal armado por
    app/bootstrap.py) — así _cargar_usd_pen_dict() lo ve disponible al toque
    en esta misma sesión, sin esperar una resincronización. Un nombre
    prolijo por periodo evita pisar otros meses, aunque
    calcular_conversion_pen() no depende del nombre (lee el período de
    adentro del PDF)."""
    nombre = f"SUNAT_TC_{periodo}.pdf"
    resultado = drive_client.upload_or_replace(script.SUNAT_TC_FOLDER_ID, nombre, content, "application/pdf")
    _escribir_en_espejo_sunat(nombre, content)
    return DriveFile(id=resultado["id"], name=resultado["name"], web_view_link=resultado.get("webViewLink", ""))


def guardar_pdf_sunat_auto(content: bytes) -> tuple[DriveFile, str | None]:
    """Igual que guardar_pdf_sunat(), pero para cuando se sube el PDF fuera
    del flujo de revisar una factura puntual (ej. cargar de antemano el mes
    que viene) — no hay ningún 'periodo faltante' ya detectado a mano, así
    que se detecta leyendo el propio contenido del PDF (mismo parser que
    usa calcular_conversion_pen). Devuelve (resultado, periodo); periodo es
    None si no se pudo detectar (el archivo igual se guarda, con un nombre
    genérico, para no perderlo)."""
    tmp = Path(tempfile.gettempdir()) / f"sunat_tmp_{uuid.uuid4().hex[:8]}.pdf"
    tmp.write_bytes(content)
    try:
        tasas = script._extraer_tasas_de_pdf_sunat(tmp)
    except Exception:
        tasas = {}
    finally:
        tmp.unlink(missing_ok=True)

    if tasas:
        primera_fecha = sorted(tasas.keys())[0]
        periodo = f"{primera_fecha[:4]}{primera_fecha[5:7]}"
    else:
        periodo = None

    nombre = f"SUNAT_TC_{periodo}.pdf" if periodo else f"SUNAT_TC_SIN_DETECTAR_{uuid.uuid4().hex[:8]}.pdf"
    resultado = drive_client.upload_or_replace(script.SUNAT_TC_FOLDER_ID, nombre, content, "application/pdf")
    _escribir_en_espejo_sunat(nombre, content)
    return DriveFile(id=resultado["id"], name=resultado["name"], web_view_link=resultado.get("webViewLink", "")), periodo


def _escribir_en_espejo_sunat(nombre: str, content: bytes) -> None:
    script.SUNAT_DIR.mkdir(parents=True, exist_ok=True)
    (script.SUNAT_DIR / nombre).write_bytes(content)
