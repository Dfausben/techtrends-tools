import json
import os
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


def save_result(result):
    """
    Guarda siempre un result.json para que más adelante podamos
    consumir el estado desde Power Automate / SharePoint.
    """

    os.makedirs("output", exist_ok=True)

    result_path = "output/result.json"

    with open(result_path, "w", encoding="utf-8") as file:
        json.dump(
            result,
            file,
            ensure_ascii=False,
            indent=2,
        )

    return result_path


def find_meta_image(soup):
    """
    Busca las etiquetas de imagen social más habituales.
    """

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
    """
    Convierte cualquier formato/modo a RGB para generar después JPEG.
    Si existe transparencia, utilizamos fondo blanco.
    """

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


def resize_image(image, max_width=1200):
    """
    Reduce imágenes demasiado grandes manteniendo proporción.
    No amplía imágenes pequeñas.
    """

    if image.width <= max_width:
        return image

    ratio = max_width / image.width

    new_height = int(
        image.height * ratio
    )

    return image.resize(
        (max_width, new_height),
        Image.Resampling.LANCZOS,
    )


def main():
    if len(sys.argv) < 3:
        print("ERROR: faltan noticiaId o URL.")
        print(
            "Uso: python resolve_og.py "
            '"<noticiaId>" "<url>"'
        )
        sys.exit(1)

    noticia_id = sys.argv[1].strip()
    page_url = sys.argv[2].strip()

    print("=" * 60)
    print("TechTrends OG resolver")
    print("=" * 60)

    print(f"Noticia ID: {noticia_id}")
    print(f"Página: {page_url}")

    #
    # 1. Descargar HTML
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
        result = {
            "noticiaId": noticia_id,
            "status": "Error",
            "stage": "pagina",
            "message": str(exc),
        }

        save_result(result)

        print()
        print("RESULTADO: ERROR")
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
            )
        )

        sys.exit(1)

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
        result = {
            "noticiaId": noticia_id,
            "status": "Error",
            "stage": "html",
            "message": str(exc),
        }

        save_result(result)

        print()
        print("RESULTADO: ERROR")
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
            )
        )

        sys.exit(1)

    #
    # 3. Buscar OG
    #

    image_url, source = find_meta_image(soup)

    if not image_url:
        result = {
            "noticiaId": noticia_id,
            "status": "SinImagen",
        }

        save_result(result)

        print()
        print("RESULTADO: SIN IMAGEN")
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
            )
        )

        return

    #
    # Puede venir una URL relativa.
    #

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
        result = {
            "noticiaId": noticia_id,
            "status": "Error",
            "stage": "imagen",
            "source": source,
            "imageUrl": image_url,
            "message": str(exc),
        }

        save_result(result)

        print()
        print("RESULTADO: ERROR")
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
            )
        )

        sys.exit(1)

    content_type = image_response.headers.get(
        "Content-Type",
        "",
    )

    original_size_kb = (
        len(image_response.content) / 1024
    )

    print(
        f"HTTP imagen: "
        f"{image_response.status_code}"
    )

    print(
        f"Content-Type: "
        f"{content_type}"
    )

    print(
        f"Tamaño original: "
        f"{original_size_kb:.1f} KB"
    )

    #
    # 5. Validar imagen con Pillow
    #

    try:
        image = Image.open(
            BytesIO(
                image_response.content
            )
        )

        image.load()

    except Exception as exc:
        result = {
            "noticiaId": noticia_id,
            "status": "Error",
            "stage": "validacion_imagen",
            "source": source,
            "imageUrl": image_url,
            "message": str(exc),
        }

        save_result(result)

        print()
        print("RESULTADO: ERROR")
        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2,
            )
        )

        sys.exit(1)

    original_format = image.format
    original_width = image.width
    original_height = image.height

    print(
        f"Formato original: "
        f"{original_format}"
    )

    print(
        f"Dimensiones originales: "
        f"{original_width}x{original_height}"
    )

    #
    # 6. Normalizar
    #

    image = convert_to_rgb(image)

    image = resize_image(
        image,
        max_width=1200,
    )

    #
    # 7. Guardar JPEG
    #

    os.makedirs(
        "output",
        exist_ok=True,
    )

    output_path = (
        f"output/{noticia_id}.jpg"
    )

    image.save(
        output_path,
        format="JPEG",
        quality=85,
        optimize=True,
    )

    final_size_kb = (
        os.path.getsize(output_path)
        / 1024
    )

    #
    # 8. Resultado estructurado
    #

    result = {
        "noticiaId": noticia_id,
        "status": "Disponible",
        "source": source,
        "pageUrl": response.url,
        "imageUrl": image_url,
        "original": {
            "format": original_format,
            "width": original_width,
            "height": original_height,
            "sizeKB": round(
                original_size_kb,
                1,
            ),
        },
        "processed": {
            "format": "JPEG",
            "width": image.width,
            "height": image.height,
            "sizeKB": round(
                final_size_kb,
                1,
            ),
            "file": output_path,
        },
    }

    save_result(result)

    print()
    print("=" * 60)
    print("RESULTADO: OK")
    print("=" * 60)

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
