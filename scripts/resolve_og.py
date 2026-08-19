import html
import json
import os
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

# ==========================================================
# MAIL BANNER
# ==========================================================

MAIL_BANNER_WIDTH = 1200
MAIL_BANNER_HEIGHT = 180

# Degradado largo y progresivo.
MAIL_GRADIENT_HEIGHT = 105
MAIL_GRADIENT_POWER = 2.2


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

    candidates.append(
        (
            10,
            f"{parsed.scheme}://{parsed.netloc}/favicon.ico"
        )
    )

    candidates.sort(
        key=lambda item: item[0]
    )

    result = []
    seen = set()

    for _, url in candidates:
        if url in seen:
            continue

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

    image = ImageOps.exif_transpose(
        image
    )

    return image


def save_og_image(image, path):
    """
    Conserva la imagen OG prácticamente original.
    """

    image = ImageOps.exif_transpose(
        image
    )

    image = convert_to_rgb(
        image
    )

    image.thumbnail(
        (2400, 2400),
        Image.Resampling.LANCZOS
    )

    image.save(
        path,
        format="JPEG",
        quality=JPEG_QUALITY,
        optimize=True
    )


def create_mail_banner(image):
    """
    Banner específico para el recap por correo.

    - 1200x180
    - crop centrado tipo COVER
    - PNG con transparencia
    - 75 px iniciales completamente visibles
    - 105 px de degradado progresivo
    - termina completamente transparente
    """

    image = ImageOps.exif_transpose(
        image
    )

    image = convert_to_rgb(
        image
    )

    # ==================================================
    # CROP CENTRADO / COVER
    # ==================================================

    banner = ImageOps.fit(
        image,
        (
            MAIL_BANNER_WIDTH,
            MAIL_BANNER_HEIGHT
        ),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5)
    )

    banner = banner.convert(
        "RGBA"
    )

    # ==================================================
    # MÁSCARA ALPHA
    # ==================================================

    alpha_mask = Image.new(
        "L",
        (
            MAIL_BANNER_WIDTH,
            MAIL_BANNER_HEIGHT
        ),
        255
    )

    draw = ImageDraw.Draw(
        alpha_mask
    )

    gradient_height = min(
        MAIL_GRADIENT_HEIGHT,
        MAIL_BANNER_HEIGHT
    )

    start_y = (
        MAIL_BANNER_HEIGHT
        - gradient_height
    )

    # ==================================================
    # DEGRADADO PROGRESIVO
    #
    # 255 = visible
    #   0 = transparente
    #
    # POWER 2.2:
    # el principio pierde muy poca opacidad y el fundido
    # se hace más evidente conforme se acerca al final.
    # ==================================================

    for y in range(
        start_y,
        MAIL_BANNER_HEIGHT
    ):
        progress = (
            y - start_y
        ) / max(
            gradient_height - 1,
            1
        )

        progress = (
            progress
            ** MAIL_GRADIENT_POWER
        )

        alpha = int(
            255 * (1 - progress)
        )

        draw.line(
            [
                (0, y),
                (
                    MAIL_BANNER_WIDTH - 1,
                    y
                )
            ],
            fill=alpha
        )

    banner.putalpha(
        alpha_mask
    )

    # Garantizamos transparencia absoluta abajo.
    final_alpha = banner.getchannel(
        "A"
    )

    final_draw = ImageDraw.Draw(
        final_alpha
    )

    final_draw.line(
        [
            (
                0,
                MAIL_BANNER_HEIGHT - 1
            ),
            (
                MAIL_BANNER_WIDTH - 1,
                MAIL_BANNER_HEIGHT - 1
            )
        ],
        fill=0
    )

    banner.putalpha(
        final_alpha
    )

    return banner


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
                canvas.width - icon.width
            ) // 2

            y = (
                canvas.height - icon.height
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

    # ==================================================
    # RUTAS
    # ==================================================

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

    mail_banner_path = os.path.join(
        noticia_dir,
        "mail-banner.png"
    )

    favicon_path = os.path.join(
        noticia_dir,
        "favicon.png"
    )

    metadata_path = os.path.join(
        noticia_dir,
        "metadata.json"
    )

    os.makedirs(
        "output",
        exist_ok=True
    )

    result_path = os.path.join(
        "output",
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
        f"{noticia_raw_base}/og-image.jpg"
    )

    mail_banner_public = (
        f"{noticia_raw_base}/mail-banner.png"
    )

    favicon_public = (
        f"{noticia_raw_base}/favicon.png"
    )

    fallback_image = (
        f"{raw_base}/assets/fallback-news.png"
    )

    fallback_favicon = (
        f"{raw_base}/assets/fallback-web.png"
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

    # ==================================================
    # PAGINA
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

            "image": fallback_image,

            "ogImage": fallback_image,

            "mailBanner": "",

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

        return

    final_url = response.url

    soup = BeautifulSoup(
        response.text,
        "html.parser"
    )

    metadata = find_metadata(
        soup,
        final_url
    )

    # ==================================================
    # FAVICON
    # ==================================================

    favicon_ok = False
    favicon_source = ""

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
    # OG + MAIL BANNER
    # ==================================================

    image_ok = False
    reason = ""

    if metadata["imageUrl"]:

        try:
            source_image = download_image(
                session=session,
                url=metadata[
                    "imageUrl"
                ],
                referer=final_url
            )

            print(
                "Imagen OG: "
                f"{source_image.width}x"
                f"{source_image.height}"
            )

            # OG original.
            save_og_image(
                source_image.copy(),
                og_image_path
            )

            # Banner corto y transparente del correo.
            mail_banner = create_mail_banner(
                source_image.copy()
            )

            mail_banner.save(
                mail_banner_path,
                format="PNG",
                optimize=True
            )

            print(
                "Mail banner generado: "
                f"{MAIL_BANNER_WIDTH}x"
                f"{MAIL_BANNER_HEIGHT} PNG"
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

        final_image = (
            og_image_public
        )

        final_og_image = (
            og_image_public
        )

        final_mail_banner = (
            mail_banner_public
        )

    else:

        status = "fallback"

        final_image = (
            fallback_image
        )

        final_og_image = (
            fallback_image
        )

        final_mail_banner = ""

    result = {
        "status": status,

        "noticiaId": noticia_id,

        "image": final_image,

        "ogImage": final_og_image,

        "mailBanner": final_mail_banner,

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

    save_json(
        metadata_path,
        result
    )

    save_json(
        result_path,
        result
    )

    print()
    print("=" * 70)

    print(
        f"RESULTADO: "
        f"{status.upper()}"
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
