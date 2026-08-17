import html
import json
import os
import re
import sys
from io import BytesIO
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageOps


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/151.0.0.0 Safari/537.36"
)

PAGE_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "*/*;q=0.8"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}

IMAGE_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}

JPEG_QUALITY = 88

BANNER_WIDTH = 1200
BANNER_HEIGHT = 420

# El degradado empieza aproximadamente al 30 %.
GRADIENT_START = 0.30

# Negro inferior: 0-255.
GRADIENT_MAX_ALPHA = 235


def clean_text(value):
    if not value:
        return ""

    value = html.unescape(str(value))
    value = " ".join(value.split())

    return value.strip()


def get_hostname(url):
    try:
        hostname = urlparse(url).netloc.lower()

        if hostname.startswith("www."):
            hostname = hostname[4:]

        return hostname

    except Exception:
        return ""


def get_meta_content(soup, key):
    key = key.lower()

    for tag in soup.find_all("meta"):
        property_value = clean_text(
            tag.get("property")
        ).lower()

        name_value = clean_text(
            tag.get("name")
        ).lower()

        if property_value == key or name_value == key:
            return clean_text(
                tag.get("content")
            )

    return ""


def get_page_title(soup):
    if soup.title:
        return clean_text(
            soup.title.get_text(" ", strip=True)
        )

    return ""


def find_favicon_candidates(soup, page_url):
    candidates = []

    for link in soup.find_all("link"):
        rel = link.get("rel")

        if not rel:
            continue

        if isinstance(rel, list):
            rel_text = " ".join(rel).lower()
        else:
            rel_text = str(rel).lower()

        if "icon" not in rel_text:
            continue

        href = clean_text(
            link.get("href")
        )

        if not href:
            continue

        absolute_url = urljoin(
            page_url,
            href
        )

        href_lower = absolute_url.lower()

        # Preferimos formatos que Pillow puede manejar
        # de forma fiable.
        if ".png" in href_lower:
            priority = 1
        elif "apple-touch-icon" in rel_text:
            priority = 2
        elif ".ico" in href_lower:
            priority = 3
        elif ".jpg" in href_lower or ".jpeg" in href_lower:
            priority = 4
        else:
            priority = 5

        candidates.append(
            (
                priority,
                absolute_url
            )
        )

    parsed = urlparse(
        page_url
    )

    # Fallback tradicional de cualquier web.
    candidates.append(
        (
            10,
            f"{parsed.scheme}://{parsed.netloc}/favicon.ico"
        )
    )

    candidates.sort(
        key=lambda item: item[0]
    )

    # Evitar repetidos.
    result = []

    seen = set()

    for _, url in candidates:
        if url not in seen:
            seen.add(url)
            result.append(url)

    return result


def find_metadata(soup, page_url):
    title = get_meta_content(
        soup,
        "og:title"
    )

    if not title:
        title = get_meta_content(
            soup,
            "twitter:title"
        )

    if not title:
        title = get_page_title(
            soup
        )

    description = get_meta_content(
        soup,
        "og:description"
    )

    if not description:
        description = get_meta_content(
            soup,
            "twitter:description"
        )

    if not description:
        description = get_meta_content(
            soup,
            "description"
        )

    site_name = get_meta_content(
        soup,
        "og:site_name"
    )

    if not site_name:
        site_name = get_hostname(
            page_url
        )

    image_url = ""
    image_source = ""

    image_candidates = [
        "og:image",
        "og:image:secure_url",
        "og:image:url",
        "twitter:image",
        "twitter:image:src",
    ]

    for key in image_candidates:
        value = get_meta_content(
            soup,
            key
        )

        if value:
            image_url = urljoin(
                page_url,
                value
            )

            image_source = key

            break

    return {
        "title": title,
        "description": description,
        "siteName": site_name,
        "imageUrl": image_url,
        "imageSource": image_source,
        "faviconCandidates": find_favicon_candidates(
            soup,
            page_url
        ),
    }


def convert_to_rgb(image):
    if image.mode == "RGB":
        return image

    if image.mode == "L":
        return image.convert(
            "RGB"
        )

    if (
        image.mode in ("RGBA", "LA")
        or "transparency" in image.info
    ):
        rgba = image.convert(
            "RGBA"
        )

        background = Image.new(
            "RGB",
            rgba.size,
            "white"
        )

        background.paste(
            rgba,
            mask=rgba.getchannel("A")
        )

        return background

    return image.convert(
        "RGB"
    )


def download_image(session, url, referer=None):
    headers = dict(
        IMAGE_HEADERS
    )

    if referer:
        headers["Referer"] = referer

    response = session.get(
        url,
        headers=headers,
        timeout=25,
        allow_redirects=True
    )

    response.raise_for_status()

    image = Image.open(
        BytesIO(
            response.content
        )
    )

    image.load()

    return image


def save_og_image(image, path):
    """
    Guarda una copia JPEG de la imagen OG.

    No hace crop.
    Solo convierte a RGB y limita imágenes
    absurdamente grandes.
    """

    image = convert_to_rgb(
        image
    )

    image.thumbnail(
        (2000, 2000),
        Image.Resampling.LANCZOS
    )

    image.save(
        path,
        format="JPEG",
        quality=JPEG_QUALITY,
        optimize=True
    )


def create_banner(image):
    """
    Usa la imagen OG original.

    Únicas transformaciones:
    - crop cover 1200x420
    - degradado negro inferior

    No añade logos, texto ni elementos.
    """

    image = convert_to_rgb(
        image
    )

    banner = ImageOps.fit(
        image,
        (
            BANNER_WIDTH,
            BANNER_HEIGHT
        ),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5)
    )

    banner = banner.convert(
        "RGBA"
    )

    overlay = Image.new(
        "RGBA",
        banner.size,
        (0, 0, 0, 0)
    )

    draw = ImageDraw.Draw(
        overlay
    )

    start_y = int(
        BANNER_HEIGHT
        * GRADIENT_START
    )

    gradient_height = (
        BANNER_HEIGHT - start_y
    )

    for y in range(
        start_y,
        BANNER_HEIGHT
    ):
        progress = (
            y - start_y
        ) / max(
            gradient_height - 1,
            1
        )

        # Curva progresiva:
        # casi invisible al principio,
        # intensa al llegar abajo.
        alpha = int(
            GRADIENT_MAX_ALPHA
            * (progress ** 1.7)
        )

        draw.line(
            [
                (0, y),
                (BANNER_WIDTH, y)
            ],
            fill=(
                0,
                0,
                0,
                alpha
            )
        )

    return Image.alpha_composite(
        banner,
        overlay
    ).convert("RGB")


def save_favicon(
    session,
    candidates,
    page_url,
    destination
):
    for favicon_url in candidates:

        try:
            print(
                f"Probando favicon: {favicon_url}"
            )

            image = download_image(
                session=session,
                url=favicon_url,
                referer=page_url
            )

            image = image.convert(
                "RGBA"
            )

            icon = ImageOps.contain(
                image,
                (112, 112),
                method=Image.Resampling.LANCZOS
            )

            canvas = Image.new(
                "RGBA",
                (128, 128),
                (0, 0, 0, 0)
            )

            x = (
                canvas.width
                - icon.width
            ) // 2

            y = (
                canvas.height
                - icon.height
            ) // 2

            canvas.alpha_composite(
                icon,
                (x, y)
            )

            canvas.save(
                destination,
                format="PNG",
                optimize=True
            )

            print(
                f"Favicon OK: {favicon_url}"
            )

            return True, favicon_url

        except Exception as exc:
            print(
                f"Favicon descartado: {exc}"
            )

    return False, ""


def save_json(path, data):
    with open(
        path,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2
        )


def main():

    if len(sys.argv) < 5:
        print(
            "ERROR: faltan parámetros."
        )

        print(
            'Uso: python resolve_og.py '
            '"<noticiaId>" "<url>" '
            '"<year>" "<month>"'
        )

        sys.exit(1)

    noticia_id = sys.argv[1].strip()
    page_url = sys.argv[2].strip()
    year = sys.argv[3].strip()
    month = sys.argv[4].strip()

    repository = os.environ.get(
        "GITHUB_REPOSITORY",
        "Dfausben/techtrends-tools"
    )

    branch = os.environ.get(
        "TECHTRENDS_BRANCH",
        "main"
    )

    raw_base = (
        "https://raw.githubusercontent.com/"
        f"{repository}/{branch}"
    )

    noticia_dir = os.path.join(
        "recap-data",
        year,
        month,
        noticia_id
    )

    os.makedirs(
        noticia_dir,
        exist_ok=True
    )

    og_image_path = os.path.join(
        noticia_dir,
        "og-image.jpg"
    )

    banner_path = os.path.join(
        noticia_dir,
        "banner.jpg"
    )

    favicon_path = os.path.join(
        noticia_dir,
        "favicon.png"
    )

    metadata_path = os.path.join(
        noticia_dir,
        "metadata.json"
    )

    output_dir = "output"

    os.makedirs(
        output_dir,
        exist_ok=True
    )

    result_path = os.path.join(
        output_dir,
        "result.json"
    )

    noticia_raw_base = (
        f"{raw_base}/"
        f"recap-data/"
        f"{year}/"
        f"{month}/"
        f"{noticia_id}"
    )

    og_image_public = (
        f"{noticia_raw_base}/"
        "og-image.jpg"
    )

    banner_public = (
        f"{noticia_raw_base}/"
        "banner.jpg"
    )

    favicon_public = (
        f"{noticia_raw_base}/"
        "favicon.png"
    )

    fallback_og = (
        f"{raw_base}/"
        "assets/fallback-news.png"
    )

    fallback_banner = (
        f"{raw_base}/"
        "assets/fallback-banner.jpg"
    )

    fallback_favicon = (
        f"{raw_base}/"
        "assets/fallback-web.png"
    )

    session = requests.Session()

    print("=" * 70)
    print("TechTrends OG Resolver")
    print("=" * 70)

    print(
        f"Noticia: {noticia_id}"
    )

    print(
        f"URL: {page_url}"
    )

    print(
        f"Destino: {noticia_dir}"
    )

    # ==================================================
    # DESCARGAR PÁGINA
    # ==================================================

    try:
        response = session.get(
            page_url,
            headers=PAGE_HEADERS,
            timeout=25,
            allow_redirects=True
        )

        response.raise_for_status()

    except Exception as exc:

        result = {
            "status": "fallback",
            "noticiaId": noticia_id,
            "image": fallback_banner,
            "ogImage": fallback_og,
            "favicon": fallback_favicon,
            "ogTitle": "",
            "ogDescription": "",
            "ogSiteName": get_hostname(
                page_url
            ),
            "sourceUrl": page_url,
            "imageSource": "",
            "faviconSource": "",
            "reason": (
                "Error descargando página: "
                f"{exc}"
            )
        }

        save_json(
            metadata_path,
            result
        )

        save_json(
            result_path,
            result
        )

        print(
            json.dumps(
                result,
                ensure_ascii=False,
                indent=2
            )
        )

        return

    final_url = response.url

    print(
        f"URL final: {final_url}"
    )

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    metadata = find_metadata(
        soup,
        final_url
    )

    print()
    print(
        f"OG title: {metadata['title']}"
    )
    print(
        f"OG description: {metadata['description']}"
    )
    print(
        f"OG site: {metadata['siteName']}"
    )
    print(
        f"OG image: {metadata['imageUrl']}"
    )

    # ==================================================
    # FAVICON
    # ==================================================

    favicon_ok = False
    favicon_source = ""

    if metadata["faviconCandidates"]:

        favicon_ok, favicon_source = save_favicon(
            session=session,
            candidates=metadata[
                "faviconCandidates"
            ],
            page_url=final_url,
            destination=favicon_path
        )

    final_favicon = (
        favicon_public
        if favicon_ok
        else fallback_favicon
    )

    # ==================================================
    # OG IMAGE + BANNER
    # ==================================================

    image_ok = False
    reason = ""

    if metadata["imageUrl"]:

        try:
            source_image = download_image(
                session=session,
                url=metadata["imageUrl"],
                referer=final_url
            )

            print(
                "Imagen OG original: "
                f"{source_image.width}x"
                f"{source_image.height}"
            )

            save_og_image(
                source_image.copy(),
                og_image_path
            )

            banner = create_banner(
                source_image.copy()
            )

            banner.save(
                banner_path,
                format="JPEG",
                quality=JPEG_QUALITY,
                optimize=True
            )

            image_ok = True

        except Exception as exc:

            reason = (
                "Error descargando/procesando "
                f"imagen OG: {exc}"
            )

            print(
                reason
            )

    else:

        reason = (
            "No se encontró og:image "
            "ni twitter:image"
        )

    # ==================================================
    # RESULTADO
    # ==================================================

    if image_ok:

        status = "og"

        final_og_image = (
            og_image_public
        )

        final_banner = (
            banner_public
        )

    else:

        status = "fallback"

        final_og_image = (
            fallback_og
        )

        final_banner = (
            fallback_banner
        )

    result = {
        "status": status,
        "noticiaId": noticia_id,

        # Imagen que utiliza el banner de Teams
        "image": final_banner,

        # Imagen OG sin crop/degradado
        "ogImage": final_og_image,

        "favicon": final_favicon,

        "ogTitle": metadata[
            "title"
        ],

        "ogDescription": metadata[
            "description"
        ],

        "ogSiteName": metadata[
            "siteName"
        ],

        "sourceUrl": final_url,

        "imageSource": metadata[
            "imageSource"
        ],

        "faviconSource": favicon_source,

        "reason": reason
    }

    # metadata permanente dentro de la noticia
    save_json(
        metadata_path,
        result
    )

    # copia temporal que consume el workflow
    save_json(
        result_path,
        result
    )

    print()
    print("=" * 70)
    print(
        f"RESULTADO: {status.upper()}"
    )
    print("=" * 70)

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2
        )
    )


if __name__ == "__main__":
    main()
