import time, requests, re
S=requests.Session(); S.headers['User-Agent']='Mozilla/5.0 (catalogo dominguezdiaz.es)'
B='https://subastas.boe.es/'
for u in ['subastas_ava.php','detalleSubasta.php?idSub=SUB-JA-2026-267973&ver=1','detalleSubasta.php?idSub=SUB-JA-2026-267973&ver=3','detalleSubasta.php?idSub=SUB-JA-2026-268586&ver=3','detalleSubasta.php?idSub=SUB-JA-2026-268586&ver=3&idLote=1','https://ovc.catastro.meh.es/OVCServWeb/OVCWcfLibres/OVCFotoFachada.svc/RecuperarFotoFachadaGet?ReferenciaCatastral=3115215VK4731E']:
    for k in range(3):
        t=time.time()
        try:
            r=S.get(u if u.startswith('http') else B+u,timeout=30); print(f'{time.time()-t:5.1f}s {r.status_code} {len(r.content):7d} {r.headers.get("content-type","")[:25]} {u[:70]}',flush=True)
            if 'idLote=' in u or u.endswith('ver=3') and '268586' in u: print('   lotes:',sorted(set(re.findall(r'idLote(?:=|%3D)(\d+)',r.text)))[:20])
        except Exception as e: print(f'{time.time()-t:5.1f}s ERROR {e} {u[:70]}',flush=True)
