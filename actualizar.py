"""Actualiza catalogo.json con las subastas abiertas del Portal de Subastas del BOE,
las fotos de la Agencia Tributaria (CC BY 4.0) y las fachadas del Catastro.
Se ejecuta cada día en GitHub Actions (.github/workflows/actualizar.yml)."""
import json, os, re, sys, time, html, datetime, concurrent.futures as cf
import requests

BASE = 'https://subastas.boe.es/'
AEAT = 'https://www2.agenciatributaria.gob.es/static_files/common/internet/dep/taiif/subastaInmuebles/data2/bienes.js'
CAT = 'https://ovc.catastro.meh.es/OVCServWeb/OVCWcfLibres/OVCFotoFachada.svc/RecuperarFotoFachadaGet?ReferenciaCatastral='
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
    r = S.post(BASE + 'subastas_ava.php', data=f, timeout=60); r.raise_for_status()
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

def ficha(item):
    sid, lots, kind, est = item; out = []
    h1 = get(BASE + 'detalleSubasta.php?idSub=' + sid + '&ver=1').text; g = rows(h1)
    docs = [html.unescape(x) for x in re.findall(r'href="(verDocumento\.php\?[^"]+)"', h1)]
    h3 = get(BASE + 'detalleSubasta.php?idSub=' + sid + '&ver=3').text
    if not lots:
        b = rows(h3)
        if kind == 'v':
            r = vivienda(sid, None, est, g, b)
            if r: out.append(r)
        else: out.append(vehiculo(sid, est, g, b, docs))
    elif kind == 'v':
        n = max([int(x) for x in re.findall(r'idLote(?:=|%3D)(\d+)', h3)] or [0])
        fallos = 0
        for k in range(1, min(n, 150) + 1):
            try: b = rows(get(BASE + 'detalleSubasta.php?idSub=' + sid + '&ver=3&idLote=' + str(k), intentos=1).text)
            except Exception:
                fallos += 1
                if fallos >= 3: break
                continue
            if not es_vivienda(b.get('Descripción', '')): continue
            r = vivienda(sid, k, est, g, b)
            if r and r.get('rc'): out.append(r)
    return out

def main():
    est = json.load(open(EST, encoding='utf-8')) if os.path.exists(EST) else {'alta': {}, 'rc_ok': [], 'rc_no': []}
    lista = []
    for kind, estado, tipo, sub in [('v','EJ','I','501'),('v','PU','I','501'),('c','EJ','V',''),('c','PU','V','')]:
        lista += [(sid, lots, kind, estado) for sid, lots in buscar(estado, tipo, sub)]
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
    print('Fichas leídas:', len(boe), '| viviendas:', sum(x['k']=='v' for x in boe), '| lotes:', sum('lo' in x for x in boe), '| vehículos:', sum(x['k']=='c' for x in boe), '| errores:', errores)
    # fotos de la Agencia Tributaria
    av = {}
    try:
        t = get(AEAT).text
        for nombre in ('inmueblesSubasta', 'vehiculosSubasta'):
            m = re.search(r'const ' + nombre + r'\s*=\s*(\[.*?\]);', t, re.S)
            for x in json.loads(m.group(1)) if m else []:
                if not x.get('fotos'): continue
                if nombre == 'inmueblesSubasta' and not (x.get('tipo') == 1 or (x.get('tipo') == 6 and re.search(r'vivienda|casa|chalet|unifamiliar', x.get('descripcion', ''), re.I))): continue
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
    for x in boe:
        c = av.get(x['id']) if 'lo' not in x else None
        if c:
            p = next((a for a in c if a.get('refCatastro', '')[:14] and a['refCatastro'][:14] == x.get('rc')), c[0])
            x['ap'] = [p['id'] + '/' + f for f in p['fotos'][:6]]
            if x['k'] == 'c':
                x.pop('im', None)
                if p.get('combustible'): x['cb'] = {'G': 'Gasolina', 'D': 'Diésel', 'E': 'Eléctrico'}.get(p['combustible'], '')
        if x['k'] == 'v' and not x.get('ap') and x.get('rc') not in ok: continue
        key = x['id'] + ('#' + str(x['lo']) if 'lo' in x else '')
        x['alta'] = est['alta'].setdefault(key, HOY)
        out.append(x)
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
