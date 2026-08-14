import html
import json
import os
import sys
from io import BytesIO
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageOps


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}

JPEG_QUALITY = 85

# Dejamos todas las previews reales en 16:9.
TARGET_WIDTH = 1200
TARGET_HEIGHT = 675


def clean_text(value):
    if not value:
        return ""

    value = html.unescape(str(value))
    value = " ".join(value.split())

    return value.strip()


def get_meta_content(soup, key):
    """
    Busca una meta tanto por property como por name,
    ignorando mayúsculas/minúsculas.
    """

    key = key.lower()

    for tag in soup.find_all("meta"):
        property_value = clean_text(tag.get("property")).lower()
        name_value = clean_text(tag.get("name")).lower()

        if property_value == key or name_value == key:
            return clean_text(tag.get("content"))

    return ""


def get_page_title(soup):
    if soup.title and soup.title.string:
        return clean_text(soup.title.string)

    return ""


def get_hostname(url):
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""


def find_metadata(soup, final_page_url):
    # -------------------------
    # TITLE
    # -------------------------

    og_title = get_meta_content(
        soup,
        "og:title",
    )

    if not og_title:
        og_title = get_page_title(soup)

    # -------------------------
    # DESCRIPTION
    # -------------------------

    og_description = get_meta_content(
        soup,
        "og:description",
    )

    if not og_description:
        og_description = get_meta_content(
            soup,
            "description",
        )

    # -------------------------
    # SITE NAME
    # -------------------------

    og_site_name = get_meta_content(
        soup,
        "og:site_name",
    )

    if not og_site_name:
        og_site_name = get_hostname(
            final_page_url
        )

    # -------------------------
    # IMAGE
    # -------------------------

    image_candidates = [
        "og:image",
        "og:image:secure_url",
        "og:image:url",
        "twitter:image",
        "twitter:image:src",
    ]

    image_url = ""
    image_source = ""

    for candidate in image_candidates:
        value = get_meta_content(
            soup,
            candidate,
        )

        if value:
            image_url = urljoin(
                final_page_url,
                value,
            )

            image_source = candidate
            break

    return {
        "title": og_title,
        "description": og_description,
        "siteName": og_site_name,
        "imageUrl": image_url,
        "imageSource": image_source,
    }


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


def normalize_image(image):
    """
    Convierte a RGB y genera una preview 16:9 homogénea.

    Esto hace que todas las tarjetas de Teams tengan
    la misma proporción independientemente del OG original.
    """

    image = convert_to_rgb(image)

    return ImageOps.fit(
        image,
        (TARGET_WIDTH, TARGET_HEIGHT),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )


def save_result(result):
    os.makedirs(
        "output",
        exist_ok=True,
    )

    with open(
        "output/result.json",
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            result,
            file,
            ensure_ascii=False,
            indent=2,
        )


def fallback_result(
    noticia_id,
    source_url,
    fallback_url,
    metadata=None,
    reason="",
):
    metadata = metadata or {}

    result = {
        "status": "fallback",
        "noticiaId": noticia_id,
        "image": fallback_url,
        "ogTitle": clean_text(
            metadata.get("title")
        ),
        "ogDescription": clean_text(
            metadata.get("description")
        ),
        "ogSiteName": clean_text(
            metadata.get("siteName")
        ) or get_hostname(source_url),
        "sourceUrl": source_url,
        "reason": clean_text(reason),
    }

    save_result(result)

    print()
    print("=" * 60)
    print("RESULTADO: FALLBACK")
    print("=" * 60)
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )


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
    month = sys.argv[4].strip()

    repository = os.environ.get(
        "GITHUB_REPOSITORY",
        "Dfausben/techtrends-tools",
    )

    branch = os.environ.get(
        "TECHTRENDS_BRANCH",
        "main",
    )

    raw_base_url = (
        f"https://raw.githubusercontent.com/"
        f"{repository}/{branch}"
    )

    fallback_url = (
        f"{raw_base_url}/assets/fallback-news.png"
    )

    output_dir = os.path.join(
        "recap-images",
        year,
        month,
    )

    image_path = os.path.join(
        output_dir,
        f"{noticia_id}.jpg",
    )

    image_public_url = (
        f"{raw_base_url}/"
        f"recap-images/"
        f"{year}/"
        f"{month}/"
        f"{noticia_id}.jpg"
    )

    print("=" * 60)
    print("TechTrends OG Resolver")
    print("=" * 60)

    print(f"Noticia ID: {noticia_id}")
    print(f"Página: {page_url}")
    print(f"Año: {year}")
    print(f"Mes: {month}")

    # --------------------------------------------------
    # 1. Descargar página
    # --------------------------------------------------

    try:
        response = requests.get(
            page_url,
            headers=HEADERS,
            timeout=25,
            allow_redirects=True,
        )

        response.raise_for_status()

    except Exception as exc:
        fallback_result(
            noticia_id=noticia_id,
            source_url=page_url,
            fallback_url=fallback_url,
            reason=f"Error descargando página: {exc}",
        )

        return

    final_page_url = response.url

    print()
    print(f"HTTP página: {response.status_code}")
    print(f"URL final: {final_page_url}")

    # --------------------------------------------------
    # 2. Parsear HTML
    # --------------------------------------------------

    try:
        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

    except Exception as exc:
        fallback_result(
            noticia_id=noticia_id,
            source_url=final_page_url,
            fallback_url=fallback_url,
            reason=f"Error interpretando HTML: {exc}",
        )

        return

    # --------------------------------------------------
    # 3. Extraer metadata
    # --------------------------------------------------

    metadata = find_metadata(
        soup,
        final_page_url,
    )

    print()
    print(f"OG Title: {metadata['title']}")
    print(
        f"OG Description: "
        f"{metadata['description']}"
    )
    print(
        f"OG Site Name: "
        f"{metadata['siteName']}"
    )
    print(
        f"Imagen encontrada: "
        f"{metadata['imageUrl']}"
    )
    print(
        f"Origen imagen: "
        f"{metadata['imageSource']}"
    )

    # --------------------------------------------------
    # 4. No hay imagen
    # --------------------------------------------------

    if not metadata["imageUrl"]:
        fallback_result(
            noticia_id=noticia_id,
            source_url=final_page_url,
            fallback_url=fallback_url,
            metadata=metadata,
            reason="No se encontró og:image ni twitter:image",
        )

        return

    # --------------------------------------------------
    # 5. Descargar imagen
    # --------------------------------------------------

    try:
        image_response = requests.get(
            metadata["imageUrl"],
            headers=HEADERS,
            timeout=25,
            allow_redirects=True,
        )

        image_response.raise_for_status()

    except Exception as exc:
        fallback_result(
            noticia_id=noticia_id,
            source_url=final_page_url,
            fallback_url=fallback_url,
            metadata=metadata,
            reason=f"Error descargando imagen: {exc}",
        )

        return

    print()
    print(
        f"HTTP imagen: "
        f"{image_response.status_code}"
    )

    print(
        "Content-Type: "
        f"{image_response.headers.get('Content-Type', '')}"
    )

    # --------------------------------------------------
    # 6. Validar imagen
    # --------------------------------------------------

    try:
        image = Image.open(
            BytesIO(
                image_response.content
            )
        )

        image.load()

    except Exception as exc:
        fallback_result(
            noticia_id=noticia_id,
            source_url=final_page_url,
            fallback_url=fallback_url,
            metadata=metadata,
            reason=f"Imagen OG no válida: {exc}",
        )

        return

    print(
        f"Formato original: {image.format}"
    )

    print(
        f"Dimensiones originales: "
        f"{image.width}x{image.height}"
    )

    # --------------------------------------------------
    # 7. Normalizar
    # --------------------------------------------------

    try:
        image = normalize_image(
            image
        )

    except Exception as exc:
        fallback_result(
            noticia_id=noticia_id,
            source_url=final_page_url,
            fallback_url=fallback_url,
            metadata=metadata,
            reason=f"Error procesando imagen: {exc}",
        )

        return

    # --------------------------------------------------
    # 8. Guardar
    # --------------------------------------------------

    os.makedirs(
        output_dir,
        exist_ok=True,
    )

    image.save(
        image_path,
        format="JPEG",
        quality=JPEG_QUALITY,
        optimize=True,
    )

    final_size = (
        os.path.getsize(image_path) / 1024
    )

    # --------------------------------------------------
    # 9. Resultado
    # --------------------------------------------------

    result = {
        "status": "og",
        "noticiaId": noticia_id,
        "image": image_public_url,
        "ogTitle": metadata["title"],
        "ogDescription": metadata["description"],
        "ogSiteName": metadata["siteName"],
        "sourceUrl": final_page_url,
        "reason": "",
    }

    save_result(result)

    print()
    print("=" * 60)
    print("RESULTADO: OG")
    print("=" * 60)

    print(f"Archivo: {image_path}")
    print(
        f"Dimensiones finales: "
        f"{image.width}x{image.height}"
    )
    print(
        f"Tamaño final: "
        f"{final_size:.1f} KB"
    )

    print()
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
