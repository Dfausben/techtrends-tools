import os
import shutil
import sys
from io import BytesIO
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from PIL import Image


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151 Safari/537.36"
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}

MAX_WIDTH = 1200
JPEG_QUALITY = 85
FALLBACK_PATH = "assets/fallback-news.jpg"


def find_meta_image(soup):
    candidates = [
        ("property", "og:image"),
        ("property", "og:image:secure_url"),
        ("name", "twitter:image"),
        ("property", "twitter:image"),
        ("name", "twitter:image:src"),
    ]

    for attribute, value in candidates:
        tag = soup.find(
            "meta",
            attrs={attribute: value},
        )

        if tag:
            content = tag.get("content")

            if content and content.strip():
                return content.strip(), value

    return None, None


def convert_to_rgb(image):
    if image.mode == "RGB":
        return image

    if image.mode == "L":
        return image.convert("RGB")

    if image.mode in ("RGBA", "LA") or "transparency" in image.info:
        rgba = image.convert("RGBA")

        background = Image.new(
            "RGB",
            rgba.size,
            "white",
        )

        background.paste(
            rgba,
            mask=rgba.getchannel("A"),
        )

        return background

    return image.convert("RGB")


def resize_image(image):
    if image.width <= MAX_WIDTH:
        return image

    ratio = MAX_WIDTH / image.width
    new_height = int(image.height * ratio)

    return image.resize(
        (MAX_WIDTH, new_height),
        Image.Resampling.LANCZOS,
    )


def save_fallback(output_path, reason):
    if not os.path.exists(FALLBACK_PATH):
        print()
        print("ERROR: no existe el fallback.")
        print(f"Ruta esperada: {FALLBACK_PATH}")
        sys.exit(1)

    os.makedirs(
        os.path.dirname(output_path),
        exist_ok=True,
    )

    shutil.copyfile(
        FALLBACK_PATH,
        output_path,
    )

    print()
    print("=" * 60)
    print("RESULTADO: FALLBACK")
    print("=" * 60)
    print(f"Motivo: {reason}")
    print(f"Fallback origen: {FALLBACK_PATH}")
    print(f"Archivo generado: {output_path}")


def main():
    if len(sys.argv) < 5:
        print("ERROR: faltan parámetros.")
        print(
            'Uso: python resolve_og.py '
            '"<noticiaId>" "<url>" "<year>" "<month>"'
        )
        sys.exit(1)

    noticia_id = sys.argv[1].strip()
    page_url = sys.argv[2].strip()
    year = sys.argv[3].strip()
    month = sys.argv[4].strip().zfill(2)

    output_dir = os.path.join(
        "recap-images",
        year,
        month,
    )

    output_path = os.path.join(
        output_dir,
        f"{noticia_id}.jpg",
    )

    print("=" * 60)
    print("TechTrends OG Resolver")
    print("=" * 60)

    print(f"Noticia ID: {noticia_id}")
    print(f"Página: {page_url}")
    print(f"Año: {year}")
    print(f"Mes: {month}")
    print(f"Destino: {output_path}")

    #
    # 1. Descargar página
    #

    try:
        response = requests.get(
            page_url,
            headers=HEADERS,
            timeout=20,
            allow_redirects=True,
        )

        response.raise_for_status()

    except Exception as exc:
        save_fallback(
            output_path,
            f"No se pudo descargar la página: {exc}",
        )
        return

    print()
    print(f"HTTP página: {response.status_code}")
    print(f"URL final: {response.url}")

    #
    # 2. Parsear HTML
    #

    try:
        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

    except Exception as exc:
        save_fallback(
            output_path,
            f"No se pudo interpretar el HTML: {exc}",
        )
        return

    #
    # 3. Buscar OG / Twitter image
    #

    image_url, source = find_meta_image(soup)

    if not image_url:
        save_fallback(
            output_path,
            "No existe og:image ni twitter:image.",
        )
        return

    image_url = urljoin(
        response.url,
        image_url,
    )

    print()
    print(f"Encontrada mediante: {source}")
    print(f"Imagen: {image_url}")

    #
    # 4. Descargar imagen
    #

    try:
        image_response = requests.get(
            image_url,
            headers=HEADERS,
            timeout=20,
            allow_redirects=True,
        )

        image_response.raise_for_status()

    except Exception as exc:
        save_fallback(
            output_path,
            f"No se pudo descargar la imagen: {exc}",
        )
        return

    print(f"HTTP imagen: {image_response.status_code}")
    print(
        "Content-Type: "
        f"{image_response.headers.get('Content-Type', '')}"
    )

    #
    # 5. Validar imagen
    #

    try:
        image = Image.open(
            BytesIO(
                image_response.content
            )
        )

        image.load()

    except Exception as exc:
        save_fallback(
            output_path,
            f"El recurso no es una imagen válida: {exc}",
        )
        return

    print(f"Formato original: {image.format}")
    print(
        f"Dimensiones originales: "
        f"{image.width}x{image.height}"
    )

    #
    # 6. Normalizar
    #

    image = convert_to_rgb(image)
    image = resize_image(image)

    #
    # 7. Crear carpeta
    #

    os.makedirs(
        output_dir,
        exist_ok=True,
    )

    #
    # 8. Guardar JPG
    #

    image.save(
        output_path,
        format="JPEG",
        quality=JPEG_QUALITY,
        optimize=True,
    )

    final_size_kb = (
        os.path.getsize(output_path) / 1024
    )

    print()
    print("=" * 60)
    print("RESULTADO: OG IMAGE")
    print("=" * 60)

    print(f"Archivo: {output_path}")
    print(
        f"Dimensiones finales: "
        f"{image.width}x{image.height}"
    )
    print(
        f"Tamaño final: "
        f"{final_size_kb:.1f} KB"
    )


if __name__ == "__main__":
    main()
