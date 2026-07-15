# -*- coding: utf-8 -*-
"""
Script de uso único (no se despliega): camina el árbol
bronze/importaciones/Gerencia_Supply_Preview/facturas_pdf/{proveedor}/{marca}/worked
y bronze/importaciones/Gerencia_Supply_Preview/sunat_tc dentro de Google Drive,
buscando el ID real de cada carpeta 'worked' por marca y el de 'sunat_tc'.

No sube ni mueve ningún archivo — los archivos ya están físicamente en su
lugar (movidos por filesystem local en la Fase 1), esto solo descubre sus
IDs de Drive para poder pegarlos en script.py (MARCAS[...]["worked_folder_id"]
y SUNAT_TC_FOLDER_ID).

Se autentica como "aplicación instalada" (abre tu navegador una sola vez,
usa el mismo oauth_client.json de la app) — corré este script vos mismo
desde una terminal local, no por la app.

Uso:
    py -3 discover_drive_ids.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from google_auth_oauthlib.flow import InstalledAppFlow

import script

_OAUTH_CLIENT_FILE = Path(__file__).resolve().parent / "oauth_client.json"
_SCOPES = ["https://www.googleapis.com/auth/drive"]


def _find_folder(service, parent_id, name):
    q = (
        f"'{parent_id}' in parents and name = '{name}' "
        f"and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    )
    resp = service.files().list(
        q=q, fields="files(id, name)",
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    archivos = resp.get("files", [])
    return archivos[0]["id"] if archivos else None


def _find_folder_by_local_path(service, root_folder_id, root_local_path, target_local_path):
    """Camina desde root_folder_id (que corresponde a root_local_path en disco)
    hasta encontrar el ID de la carpeta de Drive que corresponde a
    target_local_path, siguiendo el mismo camino de subcarpetas por nombre."""
    partes_relativas = target_local_path.relative_to(root_local_path).parts
    folder_id = root_folder_id
    for parte in partes_relativas:
        siguiente = _find_folder(service, folder_id, parte)
        if siguiente is None:
            return None
        folder_id = siguiente
    return folder_id


def main():
    # port=8501 (no port=0/aleatorio): el oauth_client.json es de tipo "Web
    # application", que exige que la URI de redirect esté pre-registrada en
    # Google Cloud Console de forma exacta — hoy solo está registrado
    # "http://localhost:8501" (el mismo que usa la app). Asegurate de que el
    # servidor Streamlit NO esté corriendo en ese puerto al ejecutar este
    # script (se pisarían).
    flow = InstalledAppFlow.from_client_secrets_file(str(_OAUTH_CLIENT_FILE), scopes=_SCOPES)
    creds = flow.run_local_server(port=8501)

    from googleapiclient.discovery import build
    service = build("drive", "v3", credentials=creds, cache_discovery=False)

    preview_local = script.BASE_PATH / "bronze/importaciones/Gerencia_Supply_Preview"
    importaciones_local = script.BASE_PATH / "bronze/importaciones"

    print("Buscando la carpeta 'importaciones' en Drive (raíz de Mi unidad del usuario logueado)...")
    # 'importaciones' está compartida directamente (no necesitamos caminar
    # desde 'Mi unidad' — Drive API puede buscar por nombre en cualquier
    # carpeta a la que el usuario tenga acceso, root='root' es el punto de
    # partida de "Mi unidad" del usuario).
    importaciones_id = _find_folder(service, "root", "importaciones")
    if importaciones_id is None:
        # Puede que 'importaciones' no cuelgue directo de la raíz del usuario
        # si la ruta local tiene más carpetas intermedias (Arquitectura_de_datos/
        # DataBase/data/bronze/importaciones) — caminamos desde la raíz por nombre.
        folder_id = "root"
        for parte in ("Arquitectura_de_datos", "DataBase", "data", "bronze", "importaciones"):
            siguiente = _find_folder(service, folder_id, parte)
            if siguiente is None:
                print(f"ERROR: no se encontró la carpeta '{parte}' en Drive bajo el padre actual.")
                print("Revisá que tu cuenta tenga acceso, o ajustá este script a mano.")
                return
            folder_id = siguiente
        importaciones_id = folder_id

    print(f"'importaciones' encontrada: {importaciones_id}")

    preview_id = _find_folder(service, importaciones_id, "Gerencia_Supply_Preview")
    if preview_id is None:
        print("ERROR: no se encontró 'Gerencia_Supply_Preview' dentro de 'importaciones'.")
        return
    print(f"'Gerencia_Supply_Preview' encontrada: {preview_id}")

    facturas_pdf_id = _find_folder(service, preview_id, "facturas_pdf")
    sunat_tc_id = _find_folder(service, preview_id, "sunat_tc")
    print(f"'facturas_pdf' encontrada: {facturas_pdf_id}")
    print(f"'sunat_tc' encontrada: {sunat_tc_id}")

    if facturas_pdf_id is None or sunat_tc_id is None:
        print("ERROR: falta alguna de las carpetas esperadas — revisá el move de la Fase 1.")
        return

    proveedor_cache = {}
    worked_ids = {}
    faltantes = []

    for marca, info in script.MARCAS.items():
        proveedor = info["proveedor"]
        if proveedor not in proveedor_cache:
            proveedor_cache[proveedor] = _find_folder(service, facturas_pdf_id, proveedor)
        proveedor_id = proveedor_cache[proveedor]
        if proveedor_id is None:
            faltantes.append(f"{marca} (proveedor '{proveedor}' no encontrado)")
            continue

        marca_id = _find_folder(service, proveedor_id, marca)
        if marca_id is None:
            faltantes.append(f"{marca} (carpeta de marca no encontrada dentro de '{proveedor}')")
            continue

        worked_id = _find_folder(service, marca_id, "worked")
        if worked_id is None:
            faltantes.append(f"{marca} (subcarpeta 'worked' no encontrada)")
            continue

        worked_ids[marca] = worked_id
        print(f"  OK  {marca}: {worked_id}")

    print(f"\nEncontradas {len(worked_ids)} de {len(script.MARCAS)} marcas.")
    if faltantes:
        print("Faltantes (revisar a mano):")
        for f in faltantes:
            print(f"  - {f}")

    salida = {"worked_folder_ids": worked_ids, "sunat_tc_folder_id": sunat_tc_id}
    out_path = Path(__file__).resolve().parent / "discover_drive_ids_output.json"
    out_path.write_text(json.dumps(salida, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nEscrito: {out_path}")

    print("\n--- Literal Python listo para pegar en script.py ---\n")
    print("WORKED_FOLDER_IDS = {")
    for marca, fid in worked_ids.items():
        print(f"    {marca!r}: {fid!r},")
    print("}")
    print(f"\nSUNAT_TC_FOLDER_ID = {sunat_tc_id!r}")


if __name__ == "__main__":
    main()
