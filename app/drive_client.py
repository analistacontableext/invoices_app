"""
Wrapper delgado sobre Google Drive API v3.

A diferencia de Google Sheets (que sigue usando la cuenta de servicio,
script.conectar_google_sheets()), las llamadas de este módulo se autentican
con las credenciales OAuth del usuario actualmente logueado
(st.session_state["drive_credentials"], guardado por app/auth.py tras el
login). Así cada persona sube/lee archivos con su propia cuota de Drive, sin
depender de que la cuenta de servicio tenga acceso especial a la carpeta
(ver Contexto del plan de migración: una cuenta de servicio no tiene cuota
propia fuera de una Unidad Compartida real, y hoy se está trabajando sobre
una carpeta personal compartida, no una Unidad Compartida).

Los parámetros supportsAllDrives/includeItemsFromAllDrives se dejan puestos
en todas las llamadas aunque hoy no hagan falta (estamos en "Mi unidad", no
en una Unidad Compartida) — así este archivo no necesita tocarse el día que
todo se mude a la Unidad Compartida real de Gerencia Supply.
"""
import io
import mimetypes
import time

import streamlit as st
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

_SCOPES = ["https://www.googleapis.com/auth/drive"]
_RETRYABLE_STATUSES = {403, 429, 500, 503}


class SinCredencialesDriveError(Exception):
    """El usuario todavía no tiene credenciales de Drive en la sesión (no
    inició sesión, o inició sesión antes de que se agregara el scope de
    Drive y todavía no volvió a loguearse)."""


def _credenciales_usuario() -> Credentials:
    datos = st.session_state.get("drive_credentials")
    if not datos:
        raise SinCredencialesDriveError(
            "No hay credenciales de Drive en la sesión — cerrá sesión y volvé a "
            "iniciar sesión con Google para otorgar el permiso de Drive."
        )
    return Credentials(
        token=datos["token"],
        refresh_token=datos["refresh_token"],
        token_uri=datos["token_uri"],
        client_id=datos["client_id"],
        client_secret=datos["client_secret"],
        scopes=datos["scopes"],
    )


def get_drive_service():
    """Construye un cliente de Drive v3 nuevo en cada llamada (barato) — así
    siempre refleja las credenciales más recientes de la sesión actual, y el
    refresco automático de token (si expiró) queda a cargo de la librería."""
    creds = _credenciales_usuario()
    if creds.expired and creds.refresh_token:
        creds.refresh(GoogleAuthRequest())
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _con_reintento(fn, max_intentos=5):
    """Reintento con backoff exponencial para errores transitorios/rate limits."""
    demora = 1.0
    for intento in range(max_intentos):
        try:
            return fn()
        except HttpError as e:
            status = getattr(e.resp, "status", None)
            if status not in _RETRYABLE_STATUSES or intento == max_intentos - 1:
                raise
            time.sleep(demora)
            demora *= 2


def _escapar(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace("'", "\\'")


def list_files_in_folder(folder_id: str, name_equals: str | None = None) -> list[dict]:
    """Lista los archivos no eliminados dentro de folder_id (paginado)."""
    service = get_drive_service()
    q = f"'{folder_id}' in parents and trashed = false"
    if name_equals is not None:
        q += f" and name = '{_escapar(name_equals)}'"

    archivos = []
    page_token = None
    while True:
        resp = _con_reintento(lambda: service.files().list(
            q=q,
            fields="nextPageToken, files(id, name, mimeType, modifiedTime, size)",
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
            pageToken=page_token,
            pageSize=200,
        ).execute())
        archivos.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return archivos


def find_folder(parent_id: str, name: str) -> str | None:
    service = get_drive_service()
    q = (
        f"'{parent_id}' in parents and name = '{_escapar(name)}' "
        f"and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )
    resp = _con_reintento(lambda: service.files().list(
        q=q, fields="files(id, name)",
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute())
    coincidencias = resp.get("files", [])
    return coincidencias[0]["id"] if coincidencias else None


def create_folder(parent_id: str, name: str) -> str:
    service = get_drive_service()
    body = {"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent_id]}
    resp = _con_reintento(lambda: service.files().create(
        body=body, fields="id", supportsAllDrives=True,
    ).execute())
    return resp["id"]


def find_or_create_folder(parent_id: str, name: str) -> str:
    return find_folder(parent_id, name) or create_folder(parent_id, name)


def download_file_bytes(file_id: str) -> bytes:
    service = get_drive_service()
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    listo = False
    while not listo:
        _, listo = _con_reintento(downloader.next_chunk)
    return buffer.getvalue()


def upload_bytes(folder_id: str, filename: str, content: bytes, mimetype: str | None = None) -> dict:
    """Crea un archivo nuevo — usar upload_or_replace() si el nombre podría
    ya existir en la carpeta y se quiere sobreescribir en vez de duplicar."""
    service = get_drive_service()
    mimetype = mimetype or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    media = MediaIoBaseUpload(io.BytesIO(content), mimetype=mimetype, resumable=False)
    body = {"name": filename, "parents": [folder_id]}
    return _con_reintento(lambda: service.files().create(
        body=body, media_body=media, fields="id, name, webViewLink",
        supportsAllDrives=True,
    ).execute())


def upload_or_replace(folder_id: str, filename: str, content: bytes, mimetype: str | None = None) -> dict:
    """Si ya existe un archivo con ese nombre exacto en la carpeta, reemplaza
    su contenido (mismo id de Drive); si no, lo crea. Replica el
    comportamiento de sobreescritura silenciosa por nombre de archivo que ya
    tenía guardar_pdf_sunat() con el filesystem local."""
    service = get_drive_service()
    mimetype = mimetype or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    media = MediaIoBaseUpload(io.BytesIO(content), mimetype=mimetype, resumable=False)

    existentes = list_files_in_folder(folder_id, name_equals=filename)
    if existentes:
        file_id = existentes[0]["id"]
        return _con_reintento(lambda: service.files().update(
            fileId=file_id, media_body=media, fields="id, name, webViewLink",
            supportsAllDrives=True,
        ).execute())

    body = {"name": filename, "parents": [folder_id]}
    return _con_reintento(lambda: service.files().create(
        body=body, media_body=media, fields="id, name, webViewLink",
        supportsAllDrives=True,
    ).execute())
