# Catálogo de subastas · dominguezdiaz.es

Lista diaria de subastas de viviendas y vehículos abiertas en el [Portal de Subastas del BOE](https://subastas.boe.es), que muestra la web [dominguezdiaz.es](https://dominguezdiaz.es).

- `actualizar.py` se ejecuta cada día en GitHub Actions y genera `catalogo.json`.
- Quita las viviendas cuya ficha indica ocupantes o que son la vivienda habitual del deudor.
- Fotos: Lista de bienes a subastar por la AEAT (licencia CC BY 4.0, https://sede.agenciatributaria.gob.es/Sede/subastas.html) y fotografías de fachada de la Dirección General del Catastro.
- `estado.json` guarda la fecha en que apareció cada subasta (etiqueta «Novedad», 7 días).

Los datos son orientativos: manda siempre la ficha oficial del BOE.
