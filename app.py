from flask import Flask, request, send_file, render_template_string, abort, jsonify
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from PIL import Image
import os, re, html, uuid, tempfile, requests, threading, shutil, zipfile
from urllib.parse import quote
from datetime import datetime

app = Flask(__name__)

SOFTR_API_KEY = os.environ.get("SOFTR_API_KEY")
SOFTR_DATABASE_ID = os.environ.get("SOFTR_DATABASE_ID")
SOFTR_TABLE_ID = os.environ.get("SOFTR_TABLE_ID")
SOFTR_ADRES_VOL_FIELD = os.environ.get("SOFTR_ADRES_VOL_FIELD", "Adres (vol)")
SOFTR_STRAATNAAM_FIELD = os.environ.get("SOFTR_STRAATNAAM_FIELD", "Straatnaam")
SOFTR_HUISNUMMER_FIELD = os.environ.get("SOFTR_HUISNUMMER_FIELD", "Huisnummer")
SOFTR_HUISLETTER_FIELD = os.environ.get("SOFTR_HUISLETTER_FIELD", "Huisletter")
SOFTR_HUISNUMMERTOEVOEGING_FIELD = os.environ.get("SOFTR_HUISNUMMERTOEVOEGING_FIELD", "Huisnummertoevoeging")
SOFTR_POSTCODE_FIELD = os.environ.get("SOFTR_POSTCODE_FIELD", "Postcode")
SOFTR_GEMEENTE_FIELD = os.environ.get("SOFTR_GEMEENTE_FIELD", "Gemeente")
SOFTR_ADRES_FIELD = os.environ.get("SOFTR_ADRES_FIELD", "Adres")  # fallback als losse velden ontbreken
SOFTR_POSTCODE_GEMEENTE_FIELD = os.environ.get("SOFTR_POSTCODE_GEMEENTE_FIELD", "Postcode & gemeente")  # fallback
SOFTR_OPDRACHTGEVER_FIELD = os.environ.get("SOFTR_OPDRACHTGEVER_FIELD", "Opdrachtgever")
SOFTR_ADVISEUR_FIELD = os.environ.get("SOFTR_ADVISEUR_FIELD", "Adviseur")
SOFTR_MEETRAPPORT_OUTPUT_FIELD = os.environ.get("SOFTR_MEETRAPPORT_OUTPUT_FIELD")
SOFTR_PLATTEGRONDEN_ZIP_FIELD = os.environ.get("SOFTR_PLATTEGRONDEN_ZIP_FIELD")
SOFTR_MEETRAPPORT_INPUT_FIELD = os.environ.get("SOFTR_MEETRAPPORT_INPUT_FIELD")  # optioneel: file-field met invoerbestanden
BASE_URL = os.environ.get("BASE_URL", "https://meetrapport-generator.onrender.com")
LOGO_URL = os.environ.get("LOGO_URL", "https://b42bc67a29.clvaw-cdnwnd.com/e47c03f3510757158cfda305a04bc579/200000168-88b2788b29/450/LogoDef8.webp?ph=b42bc67a29")
TEMP_DIR = tempfile.gettempdir()

JOBS = {}
DOWNLOADS = {}
JOBS_LOCK = threading.Lock()

GREEN = colors.HexColor("#0b5a1e")
LIGHT_GREEN = colors.HexColor("#dff0cf")
FOOTER = colors.HexColor("#eef2f7")
TEXT = colors.HexColor("#1f2937")
MUTED = colors.HexColor("#94a3b8")

HTML = """
<!doctype html><html><head><title>Meetrapport generator</title><style>
body{font-family:Arial,sans-serif;max-width:860px;margin:40px auto}.hint{color:#666;line-height:1.45;max-width:700px}
button{padding:10px 16px;cursor:pointer}.dropzone{border:2px dashed #b8b8b8;border-radius:12px;padding:24px;background:#fafafa;margin:16px 0;max-width:680px}.dropzone.dragover{border-color:#1a73e8;background:#eef5ff}.small{font-size:13px;color:#666;margin-top:4px}#progressBox{display:none;margin-top:22px;max-width:680px}.progress-wrap{height:18px;background:#eee;border-radius:999px;overflow:hidden}.progress-bar{height:18px;width:0%;background:#1a73e8;transition:width .25s}.progress-line{margin-top:10px;font-weight:700}.progress-detail{color:#666;margin-top:5px;font-size:14px}
</style></head><body><h1>Meetrapport generator</h1>
<p class="hint">Upload de volgende bestanden:<br><b>Meetstaat.png</b><br><b>[2D plattegronden].jpg</b><br><b>[3D plattegronden].jpg</b><br><b>[Woning].fml</b></p>
<form id="uploadForm" action="{{action_url}}" method="post" enctype="multipart/form-data">
<div class="dropzone" id="dropzone"><b>Bestanden</b><div class="small">Selecteer tegelijk: meetstaat, 2D plattegronden, 3D plattegronden en eventueel .fml.</div><input id="fileInput" type="file" name="files" multiple accept="image/*,application/pdf,.pdf,.fml"><div id="fileName" class="small">Geen bestanden geselecteerd</div></div>
<button id="submitBtn" type="submit">Maak meetrapport + zip</button></form>
<div id="progressBox"><div class="progress-wrap"><div id="progressBar" class="progress-bar"></div></div><div id="progressLine" class="progress-line">Voorbereiden - 0%</div><div id="progressDetail" class="progress-detail">Upload wordt gestart...</div></div>
<script>
const dz=document.getElementById('dropzone'),fi=document.getElementById('fileInput'),fn=document.getElementById('fileName'),form=document.getElementById('uploadForm'),btn=document.getElementById('submitBtn'),box=document.getElementById('progressBox'),bar=document.getElementById('progressBar'),line=document.getElementById('progressLine'),detail=document.getElementById('progressDetail');
function upd(){fn.innerText=(!fi.files||fi.files.length===0)?'Geen bestanden geselecteerd':Array.from(fi.files).map(f=>f.name).join(', ')}
fi.addEventListener('change',upd);dz.addEventListener('dragover',e=>{e.preventDefault();dz.classList.add('dragover')});dz.addEventListener('dragleave',()=>dz.classList.remove('dragover'));dz.addEventListener('drop',e=>{e.preventDefault();dz.classList.remove('dragover');fi.files=e.dataTransfer.files;upd()});
function poll(id){fetch('/meetrapport-job-status/'+id).then(r=>r.json()).then(d=>{const p=d.percent||0;bar.style.width=p+'%';line.innerText=(d.step||'Bezig')+' - '+p+'%';detail.innerText=d.detail||'';if(d.status==='done'){window.location.href='/meetrapport-job-result/'+id}else if(d.status==='error'){line.innerText='Fout - 100%';detail.innerText=d.detail||'Er ging iets mis.';btn.disabled=false;btn.innerText='Opnieuw proberen'}else{setTimeout(()=>poll(id),800)}}).catch(()=>setTimeout(()=>poll(id),1500))}
form.addEventListener('submit',e=>{e.preventDefault();if(!fi.files||fi.files.length===0){alert('Kies eerst bestanden.');return}btn.disabled=true;btn.innerText='Uploaden...';box.style.display='block';bar.style.width='3%';line.innerText='Uploaden - 3%';detail.innerText='Bestanden worden naar Render gestuurd...';fetch(form.action+'?async=1',{method:'POST',body:new FormData(form)}).then(r=>r.json()).then(d=>{if(!d.job_id)throw new Error(d.error||'Geen job_id ontvangen');btn.innerText='Bezig met verwerken...';poll(d.job_id)}).catch(err=>{line.innerText='Fout';detail.innerText=err.message;btn.disabled=false;btn.innerText='Opnieuw proberen'})});
</script></body></html>
"""

RESULT_HTML = """
<!doctype html><html><head><title>Meetrapport gemaakt</title><style>body{font-family:Arial,sans-serif;max-width:820px;margin:40px auto}.btn{display:inline-block;padding:12px 18px;background:#1a73e8;color:white;text-decoration:none;border-radius:6px;font-weight:700;margin-right:8px}.okbox{padding:12px 14px;background:#eef8f0;border:1px solid #b8dfc0;margin:18px 0}.warnbox{padding:12px 14px;background:#fff6e5;border:1px solid #ffd58a;margin:18px 0}pre{white-space:pre-wrap;background:#f7f7f7;padding:12px;border-radius:6px}</style></head><body><h1>Meetrapport gemaakt</h1>{{message|safe}}<a class="btn" href="/download/{{pdf_id}}">Download meetrapport</a><a class="btn" href="/download/{{zip_id}}">Download zip</a><h3>Samenvatting</h3><pre>{{summary}}</pre></body></html>
"""

def safe_text(v, fallback="-"):
    if v is None: return fallback
    v = str(v).strip()
    return v if v else fallback

def clean_filename(value):
    value = safe_text(value, "meetrapport")
    value = re.sub(r"[\\/:*?\"<>|]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip(" .-")
    return value or "meetrapport"

def first_value(fields, name):
    v = fields.get(name)
    if isinstance(v, list):
        if not v: return ""
        first = v[0]
        if isinstance(first, dict): return first.get("name") or first.get("filename") or first.get("url") or ""
        return str(first)
    if isinstance(v, dict): return v.get("name") or v.get("filename") or v.get("url") or ""
    return "" if v is None else str(v)

def extract_urls(value):
    urls = []
    if not value: return urls
    if isinstance(value, str):
        if value.startswith("http"): urls.append({"url": value, "name": ""})
        return urls
    if isinstance(value, list):
        for item in value: urls.extend(extract_urls(item))
        return urls
    if isinstance(value, dict):
        url = value.get("url") or value.get("fileUrl") or value.get("downloadUrl") or value.get("signedUrl")
        name = value.get("name") or value.get("filename") or value.get("fileName") or ""
        if isinstance(url, str) and url.startswith("http"):
            urls.append({"url": url, "name": name})
        else:
            for sub in value.values():
                if isinstance(sub, (dict, list, str)): urls.extend(extract_urls(sub))
    return urls

def get_softr_record(record_id):
    if not SOFTR_API_KEY or not SOFTR_DATABASE_ID or not SOFTR_TABLE_ID:
        raise RuntimeError("Softr environment variables ontbreken")
    base = f"https://tables-api.softr.io/api/v1/databases/{SOFTR_DATABASE_ID}/tables/{SOFTR_TABLE_ID}/records/{record_id}"
    headers = {"Softr-Api-Key": SOFTR_API_KEY}
    r = requests.get(base, headers=headers, timeout=30); r.raise_for_status()
    record = r.json()["data"]
    try:
        rn = requests.get(base + "?fieldNames=true", headers=headers, timeout=30)
        if rn.status_code in (200,201):
            nf = rn.json()["data"].get("fields", {})
            merged = {}; merged.update(record.get("fields", {})); merged.update(nf); record["fields"] = merged
    except Exception:
        pass
    return record

def download_url_to_file(url, folder, name=""):
    r = requests.get(url, headers={"User-Agent":"EnergievakmanMeetrapport/1.0"}, timeout=120); r.raise_for_status()
    fname = clean_filename(name or url.rsplit("/",1)[-1])
    if "." not in fname: fname += ".bin"
    path = os.path.join(folder, fname)
    with open(path, "wb") as f: f.write(r.content)
    return path

def save_download(bytes_data, filename, mimetype):
    did = uuid.uuid4().hex
    ext = ".zip" if mimetype == "application/zip" else ".pdf"
    path = os.path.join(TEMP_DIR, did + ext)
    with open(path, "wb") as f: f.write(bytes_data)
    DOWNLOADS[did] = {"path": path, "filename": filename, "mimetype": mimetype}
    return did

def absolute_download_url(did):
    d = DOWNLOADS[did]
    return BASE_URL.rstrip("/") + f"/download/{did}/{quote(d['filename'])}"

def update_softr_file_fields(record_id, pdf_url, zip_url, pdf_name, zip_name):
    if not SOFTR_API_KEY or not SOFTR_DATABASE_ID or not SOFTR_TABLE_ID:
        return False, "Softr API gegevens ontbreken in Render."
    base = f"https://tables-api.softr.io/api/v1/databases/{SOFTR_DATABASE_ID}/tables/{SOFTR_TABLE_ID}/records/{record_id}"
    headers = {"Softr-Api-Key": SOFTR_API_KEY, "Content-Type": "application/json"}
    def file_values(url, name, typ):
        return [[{"url":url,"filename":name,"type":typ}], [{"url":url,"name":name,"type":typ}], [{"fileUrl":url,"filename":name,"type":typ}], url]
    messages=[]; ok_all=True
    for field, url, name, typ, label in [
        (SOFTR_MEETRAPPORT_OUTPUT_FIELD, pdf_url, pdf_name, "application/pdf", "meetrapport"),
        (SOFTR_PLATTEGRONDEN_ZIP_FIELD, zip_url, zip_name, "application/zip", "zip")]:
        if not field:
            messages.append(f"{label}-veld ontbreekt") ; ok_all=False; continue
        ok=False; errors=[]
        for patch_url in (base, base + "?fieldNames=true"):
            for fv in file_values(url, name, typ):
                try:
                    rr = requests.patch(patch_url, headers=headers, json={"fields": {field: fv}}, timeout=30)
                    if rr.status_code in (200,201): ok=True; break
                    errors.append(f"{rr.status_code}: {rr.text[:220]}")
                except Exception as e: errors.append(str(e))
            if ok: break
        messages.append((label + " gekoppeld") if ok else (label + " niet gekoppeld: " + " | ".join(errors[-2:])))
        ok_all = ok_all and ok
    return ok_all, "; ".join(messages)

def set_job(job_id, step, percent, detail=""):
    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id].update({"step":step,"percent":max(0,min(100,int(percent))),"detail":detail})

def job_error(job_id, msg):
    with JOBS_LOCK:
        if job_id in JOBS: JOBS[job_id].update({"status":"error","step":"Fout","percent":100,"detail":msg})

def job_done(job_id, pdf_id, zip_id, message, summary):
    with JOBS_LOCK:
        if job_id in JOBS: JOBS[job_id].update({"status":"done","step":"Klaar","percent":100,"detail":"Meetrapport en zip zijn klaar.","pdf_id":pdf_id,"zip_id":zip_id,"message":message,"summary":summary})

def draw_logo(c, x, y):
    if LOGO_URL:
        try:
            r = requests.get(LOGO_URL, timeout=20); r.raise_for_status()
            img = ImageReader(BytesIO(r.content)); iw, ih = img.getSize(); scale = min(300/iw, 70/ih)
            c.drawImage(img, x, y-ih*scale, width=iw*scale, height=ih*scale, preserveAspectRatio=True, mask="auto"); return
        except Exception: pass
    c.setFont("Courier-Bold", 27); c.setFillColor(colors.black); c.drawString(x, y-34, "DE ENERGIEVAKMAN")

def draw_footer(c, footer_text):
    w,h=A4; c.setFillColor(FOOTER); c.rect(0,0,w,42,fill=1,stroke=0); c.setFillColor(MUTED); c.setFont("Helvetica",8); c.drawString(42,18,footer_text)

def fit_image(c, path, x, y, max_w, max_h):
    img = ImageReader(path); iw, ih = img.getSize(); scale = min(max_w/iw, max_h/ih)
    dw, dh = iw*scale, ih*scale
    c.drawImage(img, x+(max_w-dw)/2, y+(max_h-dh)/2, width=dw, height=dh, preserveAspectRatio=True, mask="auto")

def classify_files(paths):
    meetstaat=[]; p2d=[]; p3d=[]; other=[]
    for p in paths:
        n=os.path.basename(p).lower()
        if n.endswith(".fml"): continue
        if not n.lower().endswith((".jpg",".jpeg",".png",".webp",".pdf")): continue
        if "meetstaat" in n or "meet" in n: meetstaat.append(p)
        elif "3d" in n: p3d.append(p)
        elif "2d" in n or "plattegrond" in n or "appartement" in n or "berging" in n: p2d.append(p)
        else: other.append(p)
    return meetstaat, p2d, p3d, other

def convert_pdf_first_page_to_png(pdf_path, out_dir):
    # fallback voor PDF-invoer: eerste pagina rasteren met PyMuPDF als beschikbaar
    import fitz
    doc = fitz.open(pdf_path); page = doc.load_page(0); pix = page.get_pixmap(matrix=fitz.Matrix(2,2), alpha=False)
    out = os.path.join(out_dir, os.path.basename(pdf_path) + ".png"); pix.save(out); doc.close(); return out

def normalize_image_paths(paths, out_dir):
    out=[]
    for p in paths:
        if p.lower().endswith(".pdf"):
            try: out.append(convert_pdf_first_page_to_png(p, out_dir))
            except Exception: pass
        else:
            out.append(p)
    return out

def create_meetrapport(data, meetstaat_imgs, p2d_imgs, p3d_imgs):
    buf=BytesIO(); c=canvas.Canvas(buf, pagesize=A4); w,h=A4
    footer = "De Energievakman - " + safe_text(data.get("adres_vol") or data.get("adres"), "")
    # page 1 cover
    c.setFillColor(LIGHT_GREEN); c.rect(0,h-100,w,100,fill=1,stroke=0)
    draw_logo(c,42,h-40); c.setFont("Helvetica",10); c.setFillColor(TEXT); c.drawRightString(w-42,h-58,"Energielabels & Advies")
    c.setFillColor(TEXT); c.setFont("Helvetica-Bold",32); c.drawString(42,h-175,"Meetrapport")
    c.setFont("Helvetica",13); c.drawString(42,h-200,"NEN2580 oppervlaktemeting")
    items=[("ADRES",data.get("adres")),("POSTCODE & GEMEENTE",data.get("postcode_gemeente")),("OPDRACHTGEVER",data.get("opdrachtgever")),("ADVISEUR",data.get("adviseur"))]
    coords=[(55,h-265),(330,h-265),(55,h-330),(330,h-330)]
    for (lab,val),(x,y) in zip(items,coords):
        c.setFillColor(MUTED); c.setFont("Helvetica-Bold",8); c.drawString(x,y,lab)
        c.setFillColor(TEXT); c.setFont("Helvetica-Bold",12); c.drawString(x,y-24,safe_text(val))
    c.setStrokeColor(colors.HexColor("#d7dde5")); c.line(42,h-375,w-42,h-375); draw_footer(c,footer); c.showPage()
    # page 2 intro
    c.setFillColor(TEXT); c.setFont("Helvetica-Bold",24); c.drawString(42,h-90,"Introductie")
    text = [
        "Het meetrapport is opgesteld conform de richtlijnen van de BBMI (branche brede meetinstructie) meetinstructies 2019:",
        "Oppervlakten en inhouden van gebouwen - termen definities en bepalingsmethoden.",
        "De BBMI is een onderling afgesproken methode in de branche zonder betrokkenheid van wetgeving. De basis voor deze meetinstructie is de gebruiksoppervlakte zoals gedefinieerd in artikel 1 van het Bouwbesluit, dat verwijst naar de NEN2580.",
        "De NEN2580 vormt daarmee ook de grondslag voor deze meetinstructie.",
        "Deze meetinstructie verschilt op twee punten van de NEN2580: de BBMI categoriseert de inpandige gebruiksoppervlakte in gebruiksoppervlakte wonen en gebruiksoppervlakte overige inpandige ruimte. Daarnaast rekent de BBMI inclusief dragende binnenwanden, omdat vaak moeilijk te bepalen is of een wand dragend is.",
        "Het rapport is opgemaakt door De Energievakman, naar beste kennis en wetenschap, geheel te goeder trouw."
    ]
    y=h-130; c.setFont("Helvetica",10.5); c.setFillColor(TEXT)
    for p in text:
        words=p.split(); line=""
        for word in words:
            test=(line+" "+word).strip()
            if stringWidth(test,"Helvetica",10.5) <= w-84: line=test
            else: c.drawString(42,y,line); y-=16; line=word
        if line: c.drawString(42,y,line); y-=22
    draw_footer(c,footer); c.showPage()
    # Elke afbeelding krijgt een eigen pagina en wordt horizontaal én verticaal gecentreerd.
    for img in meetstaat_imgs:
        fit_image(c,img,42,60,w-84,h-120); draw_footer(c,footer); c.showPage()
    for img in p2d_imgs:
        fit_image(c,img,42,60,w-84,h-120); draw_footer(c,footer); c.showPage()
    for img in p3d_imgs:
        fit_image(c,img,42,60,w-84,h-120); draw_footer(c,footer); c.showPage()
    c.save(); buf.seek(0); return buf.getvalue()

def make_zip(zip_name, source_paths, pdf_bytes, pdf_name):
    b=BytesIO()
    with zipfile.ZipFile(b,"w",zipfile.ZIP_DEFLATED) as z:
        seen=set()
        for p in source_paths:
            n=os.path.basename(p)
            low=n.lower()
            # Meetstaat niet in de zip; .fml juist wel. Het meetrapport wordt hieronder toegevoegd.
            if "meetstaat" in low or low.startswith("meetstaat"):
                continue
            arc=n; i=2
            while arc in seen:
                root,ext=os.path.splitext(n); arc=f"{root} ({i}){ext}"; i+=1
            seen.add(arc); z.write(p, arc)
        z.writestr(pdf_name, pdf_bytes)
    b.seek(0); return b.getvalue()

def make_outputs(data, upload_paths, work_dir):
    meetstaat, p2d, p3d, other = classify_files(upload_paths)
    meetstaat = normalize_image_paths(meetstaat, work_dir)
    p2d = normalize_image_paths(p2d, work_dir)
    p3d = normalize_image_paths(p3d, work_dir)
    if not meetstaat: raise RuntimeError("Geen meetstaat gevonden. Zorg dat de bestandsnaam 'meetstaat' of 'meet' bevat.")
    if not p2d and not p3d: raise RuntimeError("Geen 2D/3D plattegronden gevonden.")
    base = clean_filename(data.get("adres_vol") or data.get("adres") or "Meetrapport")
    pdf_name = f"Meetrapport {base}.pdf"
    zip_name = f"{base}.zip"
    pdf_bytes = create_meetrapport(data, meetstaat, p2d, p3d)
    zip_bytes = make_zip(zip_name, upload_paths, pdf_bytes, pdf_name)
    return pdf_bytes, zip_bytes, pdf_name, zip_name, {"meetstaat":len(meetstaat),"2d":len(p2d),"3d":len(p3d)}

def combine_adres(straatnaam, huisnummer, huisletter="", toevoeging=""):
    parts = [safe_text(straatnaam, "").strip(), safe_text(huisnummer, "").strip()]
    adres = " ".join([p for p in parts if p]).strip()
    huisletter = safe_text(huisletter, "").strip()
    toevoeging = safe_text(toevoeging, "").strip()
    if huisletter:
        adres += huisletter
    if toevoeging:
        adres += ("-" if adres else "") + toevoeging
    return adres.strip()

def combine_postcode_gemeente(postcode, gemeente):
    return " ".join([safe_text(postcode, "").strip(), safe_text(gemeente, "").strip()]).strip()

def data_from_form():
    return {"adres_vol":"", "adres":"", "postcode_gemeente":"", "opdrachtgever":"", "adviseur":""}

def data_from_record(record):
    f = record.get("fields", {})
    straatnaam = first_value(f, SOFTR_STRAATNAAM_FIELD)
    huisnummer = first_value(f, SOFTR_HUISNUMMER_FIELD)
    huisletter = first_value(f, SOFTR_HUISLETTER_FIELD)
    toevoeging = first_value(f, SOFTR_HUISNUMMERTOEVOEGING_FIELD)
    postcode = first_value(f, SOFTR_POSTCODE_FIELD)
    gemeente = first_value(f, SOFTR_GEMEENTE_FIELD)
    adres = combine_adres(straatnaam, huisnummer, huisletter, toevoeging) or first_value(f, SOFTR_ADRES_FIELD)
    postcode_gemeente = combine_postcode_gemeente(postcode, gemeente) or first_value(f, SOFTR_POSTCODE_GEMEENTE_FIELD)
    return {
        "adres_vol": first_value(f, SOFTR_ADRES_VOL_FIELD) or " ".join(x for x in [adres, gemeente] if x),
        "straatnaam": straatnaam,
        "huisnummer": huisnummer,
        "huisletter": huisletter,
        "huisnummertoevoeging": toevoeging,
        "postcode": postcode,
        "gemeente": gemeente,
        "adres": adres,
        "postcode_gemeente": postcode_gemeente,
        "opdrachtgever": first_value(f, SOFTR_OPDRACHTGEVER_FIELD),
        "adviseur": first_value(f, SOFTR_ADVISEUR_FIELD),
    }

def summary(data, counts):
    return "\n".join([
        f"adres_vol: {data.get('adres_vol','')}",
        f"straatnaam: {data.get('straatnaam','')}",
        f"huisnummer: {data.get('huisnummer','')}",
        f"huisletter: {data.get('huisletter','')}",
        f"huisnummertoevoeging: {data.get('huisnummertoevoeging','')}",
        f"postcode: {data.get('postcode','')}",
        f"gemeente: {data.get('gemeente','')}",
        f"adres: {data.get('adres','')}",
        f"postcode_gemeente: {data.get('postcode_gemeente','')}",
        f"opdrachtgever: {data.get('opdrachtgever','')}",
        f"adviseur: {data.get('adviseur','')}",
        f"meetstaat_bestanden: {counts.get('meetstaat',0)}",
        f"2d_plattegronden: {counts.get('2d',0)}",
        f"3d_plattegronden: {counts.get('3d',0)}",
    ])

def process_job(job_id, record_id, paths, work_dir, form_data=None):
    try:
        set_job(job_id,"Upload ontvangen",8,"Bestanden zijn ontvangen.")
        if record_id:
            set_job(job_id,"Record ophalen",18,"Adresgegevens worden uit Softr gelezen...")
            data=data_from_record(get_softr_record(record_id))
        else:
            data=form_data or {}
        set_job(job_id,"Rapport maken",45,"Meetstaat en plattegronden worden in het rapport geplaatst...")
        pdf_bytes, zip_bytes, pdf_name, zip_name, counts = make_outputs(data, paths, work_dir)
        set_job(job_id,"Bestanden klaarzetten",68,"Downloadlinks worden aangemaakt...")
        pdf_id=save_download(pdf_bytes,pdf_name,"application/pdf"); zip_id=save_download(zip_bytes,zip_name,"application/zip")
        msg = "✅ Meetrapport en zip zijn gemaakt."
        if record_id:
            set_job(job_id,"Softr bijwerken",84,"Meetrapport en zip worden teruggeschreven naar het record...")
            ok, softr_msg = update_softr_file_fields(record_id, absolute_download_url(pdf_id), absolute_download_url(zip_id), pdf_name, zip_name)
            msg = ("✅ " if ok else "⚠️ ") + html.escape(softr_msg)
        box = f'<div class="okbox">{msg}</div>' if msg.startswith("✅") else f'<div class="warnbox">{msg}</div>'
        job_done(job_id,pdf_id,zip_id,box,summary(data,counts))
    except Exception as e:
        job_error(job_id,str(e))
    finally:
        try: shutil.rmtree(work_dir, ignore_errors=True)
        except Exception: pass

@app.route("/", methods=["GET"])
def index(): return render_template_string(HTML, action_url="/meetrapport-upload", record_id=None)

@app.route("/health", methods=["GET"])
def health(): return {"status":"ok","version":"20260626-1925"}

@app.route("/download/<download_id>", methods=["GET"])
@app.route("/download/<download_id>/<filename>", methods=["GET"])
def download(download_id, filename=None):
    if not re.match(r"^[a-f0-9]{32}$", download_id): abort(404)
    d=DOWNLOADS.get(download_id)
    if not d or not os.path.exists(d["path"]): return "Download niet meer beschikbaar. Maak het rapport opnieuw.", 404
    return send_file(d["path"], mimetype=d["mimetype"], as_attachment=True, download_name=filename or d["filename"])

@app.route("/meetrapport-upload", methods=["POST"])
def meetrapport_upload():
    files=request.files.getlist("files")
    if not files: return jsonify({"error":"Geen bestanden ontvangen"}),400
    job_id=uuid.uuid4().hex; work=os.path.join(TEMP_DIR,"meetrapport_job_"+job_id); os.makedirs(work,exist_ok=True)
    paths=[]
    for f in files:
        if not f or not f.filename: continue
        p=os.path.join(work, clean_filename(f.filename)); f.save(p); paths.append(p)
    with JOBS_LOCK: JOBS[job_id]={"status":"running","step":"Upload ontvangen","percent":5,"detail":"Verwerking wordt gestart..."}
    threading.Thread(target=process_job,args=(job_id,None,paths,work,data_from_form()),daemon=True).start()
    return jsonify({"job_id":job_id})

@app.route("/meetrapport-upload-for-record", methods=["GET"])
def missing_record_id():
    return "Record-id ontbreekt in de URL. Gebruik /meetrapport-upload-for-record/<record_id>", 400

@app.route("/meetrapport-upload-for-record/<record_id>", methods=["GET","POST"])
def upload_for_record(record_id):
    if request.method=="GET": return render_template_string(HTML, action_url=f"/meetrapport-upload-for-record/{record_id}", record_id=record_id)
    files=request.files.getlist("files")
    if not files: return jsonify({"error":"Geen bestanden ontvangen"}),400
    job_id=uuid.uuid4().hex; work=os.path.join(TEMP_DIR,"meetrapport_job_"+job_id); os.makedirs(work,exist_ok=True)
    paths=[]
    for f in files:
        if not f or not f.filename: continue
        p=os.path.join(work, clean_filename(f.filename)); f.save(p); paths.append(p)
    with JOBS_LOCK: JOBS[job_id]={"status":"running","step":"Upload ontvangen","percent":5,"detail":"Verwerking wordt gestart..."}
    threading.Thread(target=process_job,args=(job_id,record_id,paths,work,None),daemon=True).start()
    return jsonify({"job_id":job_id})

@app.route("/meetrapport-from-softr/<record_id>", methods=["GET"])
def from_softr(record_id):
    if not SOFTR_MEETRAPPORT_INPUT_FIELD: return "SOFTR_MEETRAPPORT_INPUT_FIELD ontbreekt", 500
    job_id=uuid.uuid4().hex; work=os.path.join(TEMP_DIR,"meetrapport_job_"+job_id); os.makedirs(work,exist_ok=True)
    record=get_softr_record(record_id); val=record.get("fields",{}).get(SOFTR_MEETRAPPORT_INPUT_FIELD)
    urls=extract_urls(val)
    if not urls: return "Geen invoerbestanden gevonden in Softr inputveld",404
    paths=[download_url_to_file(u["url"],work,u.get("name","")) for u in urls]
    with JOBS_LOCK: JOBS[job_id]={"status":"running","step":"Downloads ontvangen","percent":5,"detail":"Bestanden uit Softr worden verwerkt..."}
    threading.Thread(target=process_job,args=(job_id,record_id,paths,work,None),daemon=True).start()
    return render_template_string("""<!doctype html><html><head><meta http-equiv='refresh' content='1;url=/meetrapport-job-result/{{job_id}}'></head><body>Meetrapport wordt gemaakt...</body></html>""", job_id=job_id)

@app.route("/meetrapport-job-status/<job_id>", methods=["GET"])
def job_status(job_id):
    with JOBS_LOCK: job=JOBS.get(job_id)
    if not job: return jsonify({"status":"error","percent":100,"step":"Fout","detail":"Job niet gevonden"}),404
    return jsonify({"status":job.get("status","running"),"step":job.get("step","Bezig"),"percent":job.get("percent",0),"detail":job.get("detail","")})

@app.route("/meetrapport-job-result/<job_id>", methods=["GET"])
def job_result(job_id):
    with JOBS_LOCK: job=JOBS.get(job_id)
    if not job: return "Job niet gevonden",404
    if job.get("status")=="error": return f"Fout bij verwerken: {html.escape(job.get('detail','Onbekende fout'))}",500
    if job.get("status")!="done": return render_template_string("""<!doctype html><html><head><meta http-equiv='refresh' content='1'></head><body>Meetrapport is nog bezig...</body></html>"""),202
    return render_template_string(RESULT_HTML,pdf_id=job["pdf_id"],zip_id=job["zip_id"],message=job["message"],summary=job["summary"])

if __name__ == "__main__": app.run(debug=True)
