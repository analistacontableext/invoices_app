"""
Herramienta de diagnóstico para cuando un parser no reconoce una factura
(proveedor nuevo, o el proveedor cambió su plantilla): exporta la estructura
del PDF (texto por página, líneas, tablas) como JSON, para pegarla en una
conversación con el desarrollador y así arreglar el parser correspondiente
en script.py o escribir uno nuevo — sin depender de un LLM en producción.
"""
import io
import json
from pathlib import Path

import pdfplumber


def exportar_estructura_pdf(fuente: "str | Path | bytes", nombre: str) -> str:
    """
    fuente: ruta a un PDF en disco, o los bytes crudos del PDF (ej. subido en memoria,
    sin necesidad de guardarlo primero — usado en la sección "Nuevo proveedor").
    Devuelve un JSON (como string) con el texto, las líneas y las tablas de cada
    página, tal como las vería alguien escribiendo un parser nuevo.
    """
    abrir = io.BytesIO(fuente) if isinstance(fuente, (bytes, bytearray)) else fuente

    paginas = []
    with pdfplumber.open(abrir) as pdf:
        for i, page in enumerate(pdf.pages):
            texto = page.extract_text() or ""
            try:
                tablas = page.extract_tables() or []
            except Exception:
                tablas = []
            paginas.append({
                "pagina": i + 1,
                "texto": texto,
                "lineas": [l for l in texto.split("\n") if l.strip()],
                "tablas": tablas,
            })

    estructura = {
        "archivo": nombre,
        "paginas": paginas,
    }
    return json.dumps(estructura, ensure_ascii=False, indent=2)
