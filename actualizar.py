"""Actualiza catalogo.json con las subastas abiertas del Portal de Subastas del BOE y del
portal de subastas de la Seguridad Social, las fotos de la Agencia Tributaria (CC BY 4.0)
y las fachadas del Catastro.
Se ejecuta cada día en GitHub Actions (.github/workflows/actualizar.yml)."""
import json, os, re, sys, time, html, datetime, hashlib, unicodedata, concurrent.futures as cf
import requests

BASE = 'https://subastas.boe.es/'
AEAT = 'https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/taiif/subastaInmuebles/data2/bienes.js'
CAT = 'https://ovc.catastro.meh.es/OVCServWeb/OVCWcfLibres/OVCFotoFachada.svc/RecuperarFotoFachadaGet?ReferenciaCatastral='
SS = 'https://w6.seg-social.es/subastas/SubaSeControladorInter'
SUBT = {'502': 'Local comercial', '503': 'Garaje', '504': 'Trastero', '505': 'Nave industrial', '506': 'Solar', '507': 'Finca rústica', '599': 'Otros'}
RAIZ = os.path.dirname(os.path.abspath(__file__))
EST = os.path.join(RAIZ, 'estado.json')
T0 = time.time()
HOY = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=1))).date().isoformat()
S = requests.Session()
S.headers['User-Agent'] = 'Mozilla/5.0 (catalogo dominguezdiaz.es; contacto ddominguezddiaz@gmail.com)'

def get(url, intentos=3, **kw):
    for i in range(intentos):
        try:
            r = S.get(url, timeout=25, **kw)
            if r.status_code == 200: return r
        except requests.RequestException: pass
        if i < intentos - 1: time.sleep(2 + 2 * i)
    raise RuntimeError('No se pudo descargar ' + url)

def txt(s):
    s = re.sub(r'<br\s*/?>', ' ', s); s = re.sub(r'<[^>]+>', ' ', s)
    return re.sub(r'\s+', ' ', html.unescape(s)).strip()

def rows(h):
    o = {}
    for th, td in re.findall(r'<tr[^>]*>\s*<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>', h, re.S):
        k, v = txt(th), txt(td)
        if k and v and k not in o: o[k] = v
    return o

def num(s):
    m = re.search(r'[\d.]+,\d+|[\d.]+', s or '')
    return float(m.group(0).replace('.', '').replace(',', '.')) if m else None

def iso(s):
    m = re.search(r'ISO: ([^)]+)\)', s or '')
    return m.group(1)[:16] if m else ''

def buscar1(estado, tipo, sub='', orden='asc'):
    f = [('campo[0]','SUBASTA.ORIGEN'),('dato[0]',''),('campo[1]','SUBASTA.AUTORIDAD'),('dato[1]',''),
         ('campo[2]','SUBASTA.ESTADO.CODIGO'),('dato[2]',estado),('campo[3]','BIEN.TIPO'),('dato[3]',tipo),('dato[4]',sub),
         ('campo[5]','BIEN.DIRECCION'),('dato[5]',''),('campo[6]','BIEN.CODPOSTAL'),('dato[6]',''),('campo[7]','BIEN.LOCALIDAD'),('dato[7]',''),
         ('campo[8]','BIEN.COD_PROVINCIA'),('dato[8]',''),('campo[9]','SUBASTA.POSTURA_MINIMA_MINIMA_LOTES'),('dato[9]','')]
    for i in range(10, 15): f += [(f'campo[{i}]', f'SUBASTA.NUM_CUENTA_EXPEDIENTE_{i-9}'), (f'dato[{i}]', '')]
    f += [('campo[15]','SUBASTA.ID_SUBASTA_BUSCAR'),('dato[15]',''),('campo[16]','SUBASTA.ACREEDORES'),('dato[16]',''),
          ('campo[17]','SUBASTA.FECHA_FIN'),('dato[17][0]',''),('dato[17][1]',''),('campo[18]','SUBASTA.FECHA_INICIO'),('dato[18][0]',''),('dato[18][1]',''),
          ('page_hits','500'),('sort_field[0]','SUBASTA.FECHA_FIN'),('sort_order[0]',orden),('accion','Buscar')]
    for i in range(4):
        try:
            r = S.post(BASE + 'subastas_ava.php', data=f, timeout=60); r.raise_for_status(); break
        except requests.RequestException:
            if i == 3: raise
            time.sleep(20 * (i + 1))
    out = []
    for li in re.findall(r'<li class="resultado-busqueda">(.*?)</li>', r.text, re.S):
        m = re.search(r'idSub=([^&"]+)', li)
        if m: out.append((m.group(1), bool(re.search(r'lotes\)', txt(li)))))
    return out

def buscar(estado, tipo, sub=''):
    a = buscar1(estado, tipo, sub, 'asc')
    if len(a) < 500: return a
    vistos = {x[0] for x in a}   # el BOE devuelve 500 como máximo: se completa con el orden inverso
    b = [x for x in buscar1(estado, tipo, sub, 'desc') if x[0] not in vistos]
    if len(b) >= 500 - (len(a) - 500): print('Aviso: puede haber más de 1.000 resultados para', estado, tipo)
    return a + b

def ocupada(b):
    p = b.get('Situación posesoria', ''); t = p + ' ' + b.get('Información adicional', '') + ' ' + b.get('Descripción', '')
    if re.match(r'Ocupante', p, re.I): return True
    if re.search(r'consta que existen ocupantes|se encuentra ocupad|est[aá] ocupad|reside en la vivienda|arrendad[oa]|inquilin', t, re.I): return True
    if re.match(r's[ií]', b.get('Vivienda habitual', ''), re.I): return True
    if re.search(r'(^|[^o] )constituye (la )?vivienda habitual', re.sub(r'\bno constituye', 'NOx', p, flags=re.I), re.I): return True
    return False

ETQ = [(r'piscina','Piscina'),(r'jard[ií]n','Jardín'),(r'sol[aá]rium','Solárium'),(r'terraza','Terraza'),(r'garaje|plaza de aparcamiento|aparcamiento','Garaje'),
       (r'trastero','Trastero'),(r'[aá]tico','Ático'),(r'unifamiliar|chalet','Chalet / unifamiliar'),(r'adosad','Adosado'),(r'ascensor','Ascensor'),
       (r'primera l[ií]nea|frente al mar|vistas al mar','Primera línea / vistas al mar'),(r'protecci[oó]n oficial|\bVPO\b|\bVPP\b','VPO (protegida)'),
       (r'en construcci[oó]n','En construcción'),(r'en ruinas?','En ruinas'),(r'd[uú]plex','Dúplex')]
NUM = {'uno':1,'una':1,'dos':2,'tres':3,'cuatro':4,'cinco':5,'seis':6}
def org(s):
    for a, b in [('JUDICIAL EN VÍA DE APREMIO','Judicial'),('AGENCIA TRIBUTARIA','Agencia Tributaria'),('RECAUDACIÓN TRIBUTARIA','Recaudación'),
                 ('JUDICIAL VOLUNTARIA','Judicial voluntaria'),('NOTARIAL HIPOTECARIA','Notarial'),('NOTARIAL VOLUNTARIA','Notarial'),
                 ('JUDICIAL CONCURSAL','Concursal'),('ADMINISTRATIVA','Administrativa')]: s = (s or '').replace(a, b)
    return s

def es_vivienda(d):
    d = d.lower(); iv = re.search(r'vivienda|piso\b|apartamento|chalet|unifamiliar|[aá]tico|d[uú]plex|casa\b|bungalow', d)
    ig = re.search(r'plaza de (garaje|aparcamiento)|plaza de parking|trastero|local comercial|\blocal\b|solar\b|parcela', d)
    return bool(iv) and (not ig or iv.start() < ig.start())

def vivienda(sid, lo, est, g, b):
    if ocupada(b): return None
    d = b.get('Descripción', ''); t = d + ' ' + b.get('Información adicional', '')
    r = {'id': sid, 'k': 'v', 'e': est, 'o': org(g.get('Tipo de subasta')),
         'val': num(b.get('Valor Subasta') if lo else g.get('Valor subasta')), 'dep': num(b.get('Importe del depósito') if lo else g.get('Importe del depósito')),
         'fin': iso(g.get('Fecha de conclusión')), 'ini': iso(g.get('Fecha de inicio')), 'loc': b.get('Localidad', ''),
         'pr': b.get('Provincia', '').split('/')[0], 'dir': b.get('Dirección', '')[:70], 'cp': b.get('Código Postal', '')}
    if lo: r['lo'] = lo
    rc = re.sub(r'\s', '', b.get('Referencia catastral', '')).upper()
    if re.match(r'^[0-9A-Z]{14}', rc): r['rc'] = rc[:14]
    tg = [l for p, l in ETQ if re.search(p, t, re.I)]
    if tg: r['tg'] = tg
    m = re.search(r'(\d{2,3}(?:[.,]\d{1,2})?)\s?(?:m2|m²|mts|metros cuadrados)', t, re.I)
    if m: r['m2'] = m.group(1).replace('.', ',')
    m = re.search(r'(\d|uno|una|dos|tres|cuatro|cinco|seis)\s+(?:dormitorios|habitaciones)', t, re.I)
    if m: r['dor'] = NUM.get(m.group(1).lower()) or int(m.group(1))
    if b.get('Situación posesoria', '').startswith('Sin ocupantes'): r['pos'] = 'Sin ocupantes'
    return r

def vehiculo(sid, est, g, b, docs):
    r = {'id': sid, 'k': 'c', 'e': est, 'o': org(g.get('Tipo de subasta')), 'val': num(g.get('Valor subasta')), 'dep': num(g.get('Importe del depósito')),
         'fin': iso(g.get('Fecha de conclusión')), 'ini': iso(g.get('Fecha de inicio')), 'mk': b.get('Marca', ''), 'md': b.get('Modelo', ''),
         'mat': b.get('Fecha de matriculación', ''), 'd': b.get('Descripción', '')[:90], 'pr': b.get('Provincia', '').split('/')[0]}
    if b.get('Información adicional'): r['info'] = b['Información adicional'][:160]
    if b.get('Visitable'): r['vis'] = b['Visitable']
    im = []
    for h in docs:
        try:
            ct = S.head(BASE + h, timeout=15).headers.get('content-type', '')
            if 'image' in ct: im.append(h.replace('verDocumento.php?', ''))
        except requests.RequestException: pass
    if im: r['im'] = im
    return r

def inmueble(sid, lo, est, g, b, tb):
    if ocupada(b): return None
    d = b.get('Descripción', ''); t = d + ' ' + b.get('Información adicional', '')
    r = {'id': sid, 'k': 'i', 'tb': tb, 'e': est, 'o': org(g.get('Tipo de subasta')),
         'val': num(b.get('Valor Subasta') if lo else g.get('Valor subasta')), 'dep': num(b.get('Importe del depósito') if lo else g.get('Importe del depósito')),
         'fin': iso(g.get('Fecha de conclusión')), 'ini': iso(g.get('Fecha de inicio')), 'loc': b.get('Localidad', ''),
         'pr': b.get('Provincia', '').split('/')[0], 'dir': b.get('Dirección', '')[:70], 'cp': b.get('Código Postal', '')}
    if lo: r['lo'] = lo
    rc = re.sub(r'\s', '', b.get('Referencia catastral', '')).upper()
    if re.match(r'^[0-9A-Z]{14}', rc): r['rc'] = rc[:14]
    m = re.search(r'(\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?)\s?(?:m2|m²|mts|metros cuadrados)', t, re.I)
    if m: r['m2'] = m.group(1)
    if b.get('Situación posesoria', '').startswith('Sin ocupantes'): r['pos'] = 'Sin ocupantes'
    return r

def tipo_lote(h):
    m = re.search(r'Inmueble\s*\(([^)]+)\)', txt(h))
    return m.group(1).strip() if m else None   # vehículo u otro bien mueble: no va al catálogo de inmuebles

def ficha(item):
    sid, lots, kind, est, sub = item; out = []
    h1 = get(BASE + 'detalleSubasta.php?idSub=' + sid + '&ver=1').text; g = rows(h1)
    docs = [html.unescape(x) for x in re.findall(r'href="(verDocumento\.php\?[^"]+)"', h1)]
    h3 = get(BASE + 'detalleSubasta.php?idSub=' + sid + '&ver=3').text
    if not lots:
        b = rows(h3)
        if kind == 'v':
            r = vivienda(sid, None, est, g, b)
            if r: out.append(r)
        elif kind == 'i':
            tb = SUBT.get(sub, 'Otros')
            if tb == 'Otros': tb = tipo_urbana(sin_acentos(b.get('Descripción', '') + ' ' + b.get('Dirección', '')))
            r = vivienda(sid, None, est, g, b) if es_vivienda(b.get('Descripción', '')) else inmueble(sid, None, est, g, b, tb)
            if r: out.append(r)
        else: out.append(vehiculo(sid, est, g, b, docs))
    else:
        n = max([int(x) for x in re.findall(r'idLote(?:=|%3D)(\d+)', h3)] or [0])
        fallos = 0
        for k in range(1, min(n, 150) + 1):
            try: hk = get(BASE + 'detalleSubasta.php?idSub=' + sid + '&ver=3&idLote=' + str(k), intentos=1).text
            except Exception:
                fallos += 1
                if fallos >= 3: break
                continue
            b = rows(hk)
            if es_vivienda(b.get('Descripción', '')): r = vivienda(sid, k, est, g, b)
            else:
                tl = tipo_lote(hk)
                if tl is None: continue
                if tl == 'Otros':
                    t0 = txt(hk); t0 = t0[t0.find('Lote ' + str(k)):]
                    tl = tipo_urbana(sin_acentos(t0[:600]))
                r = vivienda(sid, k, est, g, b) if tl == 'Vivienda' else inmueble(sid, k, est, g, b, 'Local comercial' if tl.startswith('Local') else tl)
            if r: out.append(r)
    return out

S2 = requests.Session()
S2.headers['User-Agent'] = S.headers['User-Agent']

def ss_get(url):
    for i in range(3):
        try:
            r = S2.get(url, timeout=40)
            if r.status_code == 200:
                r.encoding = 'iso-8859-1'; return r.text
        except requests.RequestException: pass
        time.sleep(3 + 3 * i)
    raise RuntimeError('No se pudo descargar ' + url)

def entre(t, a, b):
    m = re.search(re.escape(a) + r'\s*(.*?)\s*(?:' + b + ')', t)
    return m.group(1).strip() if m else ''

def sin_acentos(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn').upper().strip()

def tipo_urbana(d):
    for p, l in [(r'TRASTERO', 'Trastero'), (r'GARAJE|APARCAMIENTO|PARKING|PLAZA DE (?:GARAJE|APARCAMIENTO)', 'Garaje'),
                 (r'\bNAVE', 'Nave industrial'), (r'\bLOCAL', 'Local comercial'), (r'SOLAR|PARCELA', 'Solar'), (r'RUSTIC|TIERRA DE|FINCA DE (?:SECANO|REGADIO)', 'Finca rústica')]:
        if re.search(p, d): return l
    return 'Otros'

def seg_social(provs):
    """Bienes de la Seguridad Social (fincas urbanas y rústicas, vehículos) con subasta futura."""
    ahora = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=1))).replace(tzinfo=None)
    norm = {sin_acentos(p): p for p in provs}
    def prov(s):
        for parte in [x.strip() for x in s.split('/')][::-1]:
            if sin_acentos(parte) in norm: return norm[sin_acentos(parte)]
        return s.split('/')[-1].strip().title()
    out = []
    for codigo in ('0102', '0101', '0211'):
        S2.cookies.clear()
        ss_get('https://w6.seg-social.es/subastas/')
        h0 = ss_get(SS + '?opcion=10&EMB_TIPOBIEN=' + codigo + '&ok=Continuar')
        print('  SS', codigo, 'paso 2:', re.sub(r'\s+', ' ', txt(h0))[300:420], flush=True)
        filas, p = [], 1
        while p <= 80:
            h = ss_get(f'{SS}?opcion=8&tipoOperacion=1' if p == 1 else f'{SS}?pagina={p}&opcion=8&tipoOperacion=1')
            for cap, tabla in re.findall(r'<caption>(.*?)</caption>(.*?)</table>', h, re.S):
                pr = txt(cap).split(' - ')[1].strip() if ' - ' in txt(cap) else ''
                for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', tabla, re.S):
                    m = re.search(r'EMB_ID=(\d+)', tr); tds = [txt(x) for x in re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)]
                    if m and len(tds) >= 7: filas.append((m.group(1), pr, tds))
            if p == 1: print('  SS', codigo, 'resultados:', len(filas), re.sub(r'\s+', ' ', txt(h))[300:400], flush=True)
            if f'pagina={p + 1}&' not in h: break
            p += 1
        for emb, pr, tds in filas:
            fm = re.match(r'(\d{2})/(\d{2})/(\d{4})\s+(\d{2}:\d{2})', tds[6])
            if not fm: continue
            fin = f'{fm.group(3)}-{fm.group(2)}-{fm.group(1)}T{fm.group(4)}'
            if datetime.datetime.fromisoformat(fin) <= ahora: continue
            try: t = txt(ss_get(f'{SS}?opcion=13&EMB_ID={emb}&opcion2=1&tipoOperacion=1'))
            except Exception: continue
            gen = entre(t, 'Descripción General del Bien:', 'Descripción Detallada:')
            det = entre(t, 'Descripción Detallada:', r'Marca:|Localización:|Subasta Fecha:')
            lote = entre(t, 'Lote: Número', r'\.') or '1'
            exp = re.sub(r'\D', '', entre(t, 'Expediente:', r'Mostrando|$'))
            lug = entre(t, 'Lugar:', r'Lote:')
            todo = (gen + ' ' + det).upper()
            r = {'src': 'ss', 'o': 'Seguridad Social', 'e': 'EJ', 'val': num(tds[5]), 'tas': num(tds[2]),
                 'car': 0 if 'SIN CARGA' in tds[3].upper() else num(tds[3]), 'fin': fin, 'dep': round(num(tds[5]) * 0.25, 2) if num(tds[5]) else None, 'pr': prov(pr), 'lug': lug[:80]}
            if codigo == '0211':
                mat = entre(t, 'Matrícula:', r'Bastidor:|Subasta')
                r.update({'k': 'c', 'mk': entre(t, 'Marca:', 'Modelo:'), 'md': entre(t, 'Modelo:', 'Matrícula:'),
                          'mat': (re.search(r'PRIMERA MATRICULACION:\s*([\d/-]+)', todo) or [None, ''])[1], 'd': gen[:90], 'info': det[:160]})
                cb = re.search(r'COMBUSTIBLE:\s*(DIESEL|DIÉSEL|GASOLINA|ELECTRICO|ELÉCTRICO|HIBRIDO|HÍBRIDO)', todo)
                if cb: r['cb'] = {'D': 'Diésel', 'G': 'Gasolina', 'E': 'Eléctrico', 'H': 'Híbrido'}[sin_acentos(cb.group(1))[0]]
                clave = mat or hashlib.md5(gen.encode()).hexdigest()[:6]
            else:
                if re.search(r'OCUPAD|ARRENDAD|INQUILIN|VIVIENDA HABITUAL DEL DEUDOR', todo): continue
                loc = entre(t, 'Localización:', r'Subasta Fecha:')
                mc = re.search(r'\((\d{5})\)\s*(.*)$', loc)
                r.update({'dir': (loc[:mc.start()] if mc else loc).strip()[:70], 'cp': mc.group(1) if mc else '', 'loc': mc.group(2).strip() if mc else ''})
                rc = re.search(r'REF(?:ERENCIA)?\.?\s*CATASTRAL:?\s*([0-9A-Z]{14})', todo)
                if rc: r['rc'] = rc.group(1)
                m = re.search(r'(\d{1,3}(?:\.\d{3})*(?:,\d{1,2})?)\s?(?:M2|M²|METROS CUADRADOS)', todo)
                if m and (num(m.group(1)) or 0) >= 20: r['m2'] = m.group(1)
                if codigo == '0102' and es_vivienda(gen + ' ' + det):
                    r['k'] = 'v'
                    tg = [l for pat, l in ETQ if re.search(pat, gen + ' ' + det, re.I)]
                    if tg: r['tg'] = tg
                    m = re.search(r'(\d|UNO|UNA|DOS|TRES|CUATRO|CINCO|SEIS)\s+(?:DORMITORIOS|HABITACIONES)', todo)
                    if m: r['dor'] = NUM.get(m.group(1).lower()) or int(m.group(1))
                else:
                    r.update({'k': 'i', 'tb': 'Finca rústica' if codigo == '0101' else tipo_urbana(todo)})
                clave = r.get('rc') or hashlib.md5(gen.encode()).hexdigest()[:6]
            r['id'] = 'SS-' + exp + '-L' + lote + '-' + clave
            r['gen'] = gen[:90]
            out.append(r)
    vistos, res = set(), []
    for x in out:
        if x['id'] not in vistos: vistos.add(x['id']); res.append(x)
    return res

def main():
    est = json.load(open(EST, encoding='utf-8')) if os.path.exists(EST) else {'alta': {}, 'rc_ok': [], 'rc_no': []}
    lista = []
    busquedas = [('v','EJ','I','501'),('v','PU','I','501'),('c','EJ','V',''),('c','PU','V','')] + [('i', e, 'I', s) for s in SUBT for e in ('EJ', 'PU')]
    vistos = set()
    for kind, estado, tipo, sub in busquedas:
        for sid, lots in buscar(estado, tipo, sub):
            if sid not in vistos: vistos.add(sid); lista.append((sid, lots, kind, estado, sub))
    print('Subastas encontradas en el BOE:', len(lista))
    if len(lista) < 100: sys.exit('Muy pocas subastas: algo falla en el BOE. No se actualiza.')
    boe, errores = [], 0
    with cf.ThreadPoolExecutor(5) as ex:
        def seguro(it):
            try: return ficha(it)
            except Exception as e: return e
        for n, res in enumerate(ex.map(seguro, lista), 1):
            if isinstance(res, Exception): errores += 1
            else: boe += res
            if n % 50 == 0: print(f'  {n}/{len(lista)} fichas · {int(time.time()-T0)} s', flush=True)
    print('Fichas leídas:', len(boe), '| viviendas:', sum(x['k']=='v' for x in boe), '| otros inmuebles:', sum(x['k']=='i' for x in boe), '| lotes:', sum('lo' in x for x in boe), '| vehículos:', sum(x['k']=='c' for x in boe), '| errores:', errores)
    # Seguridad Social (si falla, se sigue solo con el BOE)
    try:
        ss = seg_social({x['pr'] for x in boe if x.get('pr')})
        print('Seguridad Social:', len(ss), '| viviendas:', sum(x['k']=='v' for x in ss), '| otros inmuebles:', sum(x['k']=='i' for x in ss), '| vehículos:', sum(x['k']=='c' for x in ss))
        boe += ss
    except Exception as e: print('Aviso Seguridad Social:', e)
    # fotos de la Agencia Tributaria
    av = {}
    try:
        t = get(AEAT).text
        for nombre in ('inmueblesSubasta', 'vehiculosSubasta'):
            m = re.search(r'const ' + nombre + r'\s*=\s*(\[.*?\]);', t, re.S)
            for x in json.loads(m.group(1)) if m else []:
                if not x.get('fotos'): continue
                av.setdefault(x['subasta'], []).append(x)
    except Exception as e: print('Aviso AEAT:', e)
    # fachadas del Catastro (solo referencias nuevas)
    ok, no = set(est['rc_ok']), set(est['rc_no'])
    nuevas = sorted({x['rc'] for x in boe if x.get('rc')} - ok - no)
    def foto(rc):
        try:
            r = S.get(CAT + rc, timeout=40); return rc, r.status_code == 200 and r.headers.get('content-type', '').startswith('image') and len(r.content) > 2000
        except requests.RequestException: return rc, None
    with cf.ThreadPoolExecutor(6) as ex:
        for rc, tiene in ex.map(foto, nuevas):
            if tiene: ok.add(rc)
            elif tiene is False: no.add(rc)
    print('Fotos AEAT:', len(av), '| referencias catastrales nuevas:', len(nuevas), '| con foto:', len(set(nuevas) & ok), '| sin respuesta:', len(set(nuevas) - ok - no))
    out = []
    # La primera vez con los nuevos tipos de bien no se marcan todos como «Novedad»
    alta_nueva = HOY if est.get('v2') else (datetime.date.fromisoformat(HOY) - datetime.timedelta(days=8)).isoformat()
    for x in boe:
        c = av.get(x['id']) if 'lo' not in x else None
        p = None
        if c:
            p = next((a for a in c if a.get('refCatastro', '')[:14] and a['refCatastro'][:14] == x.get('rc')), c[0] if len(c) == 1 else None)
        if p:
            x['ap'] = [p['id'] + '/' + f for f in p['fotos'][:6]]
            if x['k'] == 'c':
                x.pop('im', None)
                if p.get('combustible'): x['cb'] = {'G': 'Gasolina', 'D': 'Diésel', 'E': 'Eléctrico'}.get(p['combustible'], '')
        if x.get('rc') and x['rc'] not in ok: x['nf'] = 1   # sin foto de fachada en el Catastro
        key = x['id'] + ('#' + str(x['lo']) if 'lo' in x else '')
        x['alta'] = est['alta'].setdefault(key, alta_nueva)
        out.append(x)
    est['v2'] = 1
    anteriores = len(est['alta'])
    if anteriores and len(out) < 0.6 * min(anteriores, 400): sys.exit(f'El catálogo cae de golpe ({len(out)} frente a {anteriores}). No se actualiza.')
    vig = {x['id'] + ('#' + str(x['lo']) if 'lo' in x else '') for x in out}
    est['alta'] = {k: v for k, v in est['alta'].items() if k in vig}
    est['rc_ok'], est['rc_no'] = sorted(ok), sorted(no)
    d = HOY.split('-'); fecha = f'{d[2]}/{d[1]}/{d[0]}'
    json.dump({'fecha': fecha, 'fuente': 'Portal de Subastas del BOE; fotos: Agencia Tributaria (CC BY 4.0) y Dirección General del Catastro', 'subastas': out},
              open(os.path.join(RAIZ, 'catalogo.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    json.dump(est, open(EST, 'w', encoding='utf-8'), ensure_ascii=False)
    nov = [x for x in out if x['alta'] == HOY]
    print(f'Tiempo total: {int(time.time()-T0)} s')
    print(f'Catálogo: {len(out)} subastas ({sum(x["k"]=="v" for x in out)} viviendas, {sum(x["k"]=="c" for x in out)} vehículos). Novedades hoy: {len(nov)}')
    for x in nov[:30]: print(' -', x['id'], x.get('lo', ''), x.get('loc') or x.get('mk', ''), x.get('pr', ''), x.get('val'))

if __name__ == '__main__':
    main()
