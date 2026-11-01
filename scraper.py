"""Actualiza data.json con los remates de asorematespy.com.
Uso personal. Pide el sitemap, y solo visita las paginas nuevas o modificadas."""
import re, json, time, sys, os, datetime as dt
import requests
from bs4 import BeautifulSoup

SITEMAP = "https://www.asorematespy.com/event-pages-sitemap.xml"
OUT = "data.json"
UA = {"User-Agent": "Mozilla/5.0 (lector personal de remates publicos)"}
PAUSA = 1.5  # segundos entre paginas, para no molestar al sitio
MESES = {"ene": 1, "enero": 1, "feb": 2, "febrero": 2, "mar": 3, "marzo": 3, "abr": 4, "abril": 4,
         "may": 5, "mayo": 5, "jun": 6, "junio": 6, "jul": 7, "julio": 7, "ago": 8, "agosto": 8,
         "sep": 9, "set": 9, "sept": 9, "septiembre": 9, "setiembre": 9, "oct": 10, "octubre": 10,
         "nov": 11, "noviembre": 11, "dic": 12, "diciembre": 12}


def desde_slug(slug):
    s = slug[len("suspendido-"):] if slug.startswith("suspendido-") else slug
    m = re.search(r"(inmueble|vehiculos?|camion|tractor|excavadora|escavadora|cosechadora|semirremolque|"
                  r"retroexcavadora|bienes-muebles|titulo|gran-remate|2da-subasta)", s)
    rem = s[:m.start()].strip("-").replace("-", " ").title() if m else ""
    rest = s[m.start():] if m else s
    if rest.startswith("inmueble"):
        tipo = "Inmueble"
    elif re.match(r"(tractor|excavadora|escavadora|cosechadora|semirremolque|retroexcavadora)", rest) or "agricola" in rest:
        tipo = "Maquinaria"
    elif re.match(r"(vehiculo|camion)", rest):
        tipo = "Vehículo"
    else:
        tipo = "Otro"
    d = re.search(r"(?:distrito-?(?:de-|la-)?|dto-)(.*)", rest)
    det = re.sub(r"-\d+$", "", d.group(1)).replace("-", " ").title() if (tipo == "Inmueble" and d) \
        else re.sub(r"^vehiculos?-?", "", rest).replace("-", " ").title()
    return rem, tipo, det, slug.startswith("suspendido-")


def parsear(html):
    soup = BeautifulSoup(html, "html.parser")
    texto = soup.get_text("\n")
    og = soup.find("meta", property="og:description")
    desc = (og.get("content") if og else "") or ""
    r = {}
    # fecha y hora del remate
    m = re.search(r"El\s+d[ií]a\s+(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de(?:l)?\s+(\d{4}).{0,60}?(\d{1,2})[:.](\d{2})\s*h",
                  texto, re.S | re.I)
    if not m:
        m = re.search(r"(\d{1,2})\s+([a-záéíóú]{3,10})\.?\s+(\d{4}),\s*(\d{1,2}):(\d{2})", texto, re.I)
    if m and m.group(2).lower() in MESES:
        r["fecha"] = "%04d-%02d-%02d" % (int(m.group(3)), MESES[m.group(2).lower()], int(m.group(1)))
        r["hora"] = "%02d:%02d" % (int(m.group(4)), int(m.group(5)))
    # caratula y expediente
    q = re.search(r'"([^"]{8,})"', desc) or re.search(r'caratulad[oa]s?:?\s*"([^"]{8,})"', texto, re.I)
    if q:
        r["caratula"] = re.sub(r"\s+", " ", q.group(1)).strip()
    e = re.search(r"expte\.?\s*N[°º]\s*[\d./]+(?:,?\s*(?:del\s+)?a[ñn]o\s*\d{4})?", desc + " " + texto, re.I)
    if e:
        r["expediente"] = e.group(0)
    # juzgado
    j = re.search(r"(Juzgado[^,;\n]{5,140}?(?:Turno|Sala))", texto)
    if j:
        r["juzgado"] = re.sub(r"\s+", " ", j.group(1)).strip()
    # base (mejor esfuerzo: verificar siempre en el edicto)
    b = re.search(r"base[^.\n]{0,100}?((?:Gs\.?|G\.|₲|USD|U\$S|\$)\s*[\d.,]+)", texto, re.I)
    if b:
        r["base"] = b.group(1).strip()
    c = soup.find("meta", property="og:url")
    if c and c.get("content"):
        r["canonical"] = c["content"]
    if re.search(r"suspendid", texto[:3000], re.I):
        r["suspendido_texto"] = True
    return r


def main():
    hoy = dt.date.today().isoformat()
    try:
        old = {x["url"]: x for x in json.load(open(OUT, encoding="utf-8"))["items"]}
    except Exception:
        old = {}
    resp = requests.get(SITEMAP, headers=UA, timeout=30)
    resp.raise_for_status()
    urls = re.findall(r"<loc>(.*?)</loc>\s*<lastmod>(.*?)</lastmod>", resp.text, re.S)
    if len(urls) < 20:
        sys.exit("Sitemap sospechosamente corto, no toco data.json")
    items, nuevos, fallos = [], 0, 0
    for url, lastmod in urls:
        slug = url.rstrip("/").split("/")[-1]
        rem, tipo, det, susp = desde_slug(slug)
        it = old.get(url, {"url": url, "primera_vez": hoy})
        if url not in old:
            nuevos += 1
        necesita = (url not in old or it.get("lastmod") != lastmod or
                    (not it.get("fecha") and it.get("revisado") != hoy))
        it.update({"lastmod": lastmod, "rematador": rem, "tipo": tipo, "detalle": det, "suspendido": susp})
        if necesita:
            try:
                p = requests.get(url, headers=UA, timeout=30)
                p.raise_for_status()
                it.update(parsear(p.text))
                it["revisado"] = hoy
            except Exception as ex:
                fallos += 1
                print("No pude leer", url, ex)
            time.sleep(PAUSA)
        if it.get("suspendido_texto"):
            it["suspendido"] = True
        items.append(it)
    sin_fecha = sum(1 for i in items if not i.get("fecha"))
    print("Total %d | nuevos %d | fallos %d | sin fecha %d" % (len(items), nuevos, fallos, sin_fecha))
    json.dump({"actualizado": dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"), "items": items},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False)


if __name__ == "__main__":
    main()
