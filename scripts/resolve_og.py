import os
import sys
from io import BytesIO
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from PIL import Image


def find_meta_image(soup):
    candidates = [
        ("property", "og:image"),
        ("property", "og:image:secure_url"),
        ("name", "twitter:image"),
        ("property", "twitter:image"),
    ]

    for attribute, value in candidates:
        tag = soup.find("meta", attrs={attribute: value})

        if tag and tag.get("content"):
            return tag.get("content").strip(), value

    return None, None


def main():
    if len(sys.argv) < 2:
        print("ERROR: falta la URL.")
        sys.exit(1)

    page_url = sys.argv[1].strip()

    print("=" * 60)
    print("TechTrends OG resolver")
    print("=" * 60)
    print(f"Página: {page_url}")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/151 Safari/537.36"
        )
    }

    try:
        response = requests.get(
            page_url,
            headers=headers,
            timeout=20,
            allow_redirects=True,
        )
        response.raise_for_status()
    except Exception as exc:
        print(f"ERROR descargando la página: {exc}")
        sys.exit(1)

    print(f"HTTP página: {response.status_code}")
    print(f"URL final: {response.url}")

    soup = BeautifulSoup(response.text, "html.parser")

    image_url, source = find_meta_image(soup)

    if not image_url:
        print()
        print("RESULTADO: SIN IMAGEN")
        print("No se encontró og:image ni twitter:image.")
        return

    image_url = urljoin(response.url, image_url)

    print()
    print(f"Encontrada mediante: {source}")
    print(f"Imagen: {image_url}")

    try:
        image_response = requests.get(
            image_url,
            headers=headers,
            timeout=20,
            allow_redirects=True,
        )
        image_response.raise_for_status()
    except Exception as exc:
        print(f"ERROR descargando la imagen: {exc}")
        sys.exit(1)

    content_type = image_response.headers.get("Content-Type", "")
    size_kb = len(image_response.content) / 1024

    print(f"HTTP imagen: {image_response.status_code}")
    print(f"Content-Type: {content_type}")
    print(f"Tamaño original: {size_kb:.1f} KB")

    try:
        image = Image.open(BytesIO(image_response.content))
        image.load()
    except Exception as exc:
        print(f"ERROR: la URL encontrada no parece una imagen válida: {exc}")
        sys.exit(1)

    print(f"Formato original: {image.format}")
    print(f"Dimensiones: {image.width}x{image.height}")

    os.makedirs("output", exist_ok=True)

    if image.mode not in ("RGB", "L"):
        background = Image.new("RGB", image.size, "white")

        if "A" in image.getbands():
            background.paste(image, mask=image.getchannel("A"))
        else:
            background.paste(image)

        image = background
    elif image.mode == "L":
        image = image.convert("RGB")

    max_width = 1200

    if image.width > max_width:
        ratio = max_width / image.width
        new_height = int(image.height * ratio)
        image = image.resize(
            (max_width, new_height),
            Image.Resampling.LANCZOS
        )

    output_path = "output/og-image.jpg"

    image.save(
        output_path,
        format="JPEG",
        quality=85,
        optimize=True,
    )

    final_size_kb = os.path.getsize(output_path) / 1024

    print()
    print("RESULTADO: OK")
    print(f"Archivo generado: {output_path}")
    print(f"Dimensiones finales: {image.width}x{image.height}")
    print(f"Tamaño final: {final_size_kb:.1f} KB")


if __name__ == "__main__":
    main()
