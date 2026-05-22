#!/usr/bin/env python3
"""
JHora extraction server — http://localhost:8080
GET  /        → input form
POST /extract → runs jhora_extract.sh, returns parsed JSON
"""

import json, os, subprocess, sys, re
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse, parse_qsl
from datetime import datetime

# ── Astrology view constants ──────────────────────────────────────────────────

_SIGN_LIST = ['Aries','Taurus','Gemini','Cancer','Leo','Virgo',
              'Libra','Scorpio','Sagittarius','Capricorn','Aquarius','Pisces']
_SIGN_NUM  = {n: i+1 for i, n in enumerate(_SIGN_LIST)}
_SIGN_ABBS = ['Ar','Ta','Ge','Cn','Le','Vi','Li','Sc','Sg','Cp','Aq','Pi']
_SIGN_ABB  = dict(zip(_SIGN_LIST, _SIGN_ABBS))

_PABBR = {
    'Lagna':'As','Sun':'Su','Moon':'Mo','Mars':'Ma',
    'Mercury':'Me','Jupiter':'Ju','Venus':'Ve','Saturn':'Sa',
    'Rahu':'Ra','Ketu':'Ke','Maandi':'Md','Gulika':'Gk',
    'Hora Lagna':'HL','Ghati Lagna':'GL','Bhava Lagna':'BL',
}
_PCOLOR = {
    'Lagna':'#ea580c',
    'Sun':'#3b82f6','Moon':'#3b82f6',
    'Mars':'#ef4444','Saturn':'#64748b','Rahu':'#8b5cf6','Ketu':'#06b6d4',
    'Mercury':'#10b981','Jupiter':'#f59e0b','Venus':'#a855f7',
    'Maandi':'#94a3b8','Gulika':'#94a3b8',
    'Hora Lagna':'#cbd5e1','Ghati Lagna':'#cbd5e1','Bhava Lagna':'#cbd5e1',
}
_KARAKA_ABB = {
    'Atmakaraka':'AK','Amatyakaraka':'AmK','Bhratrukaraka':'BK',
    'Matrukaraka':'MK','Pitrukaraka':'PiK','Putrakaraka':'PK',
    'Gnatikaraka':'GK','Darakaraka':'DK',
}
_NAK_ABB = {
    'Ashwini':'Aswi','Bharani':'Bhar','Krittika':'Krit',
    'Rohini':'Rohi','Mrigashira':'Mrig','Ardra':'Ardr',
    'Punarvasu':'Puna','Pushya':'Push','Ashlesha':'Asre',
    'Magha':'Magh','Purva Phalguni':'PPha','Uttara Phalguni':'UPha',
    'Hasta':'Hast','Chitra':'Chit','Swati':'Swat',
    'Vishakha':'Vish','Anuradha':'Anur','Jyeshtha':'Jyes',
    'Mula':'Mula','Purva Ashadha':'PAsh','Uttara Ashadha':'UAsh',
    'Shravana':'Srav','Dhanishtha':'Dhan','Shatabhisha':'Sata',
    'Purva Bhadrapada':'PBha','Uttara Bhadrapada':'UBha','Revati':'Reva',
    'Aasresha':'Asre','Dhanishta':'Dhan',
}
_NI_POLYS = {
    1: [[.5,0],[.25,.25],[.5,.5],[.75,.25]],
    2: [[0,0],[.5,0],[.25,.25]],
    3: [[0,0],[0,.5],[.25,.25]],
    4: [[.25,.25],[0,.5],[.25,.75],[.5,.5]],
    5: [[0,.5],[.25,.75],[0,1]],
    6: [[.5,1],[.25,.75],[0,1]],
    7: [[.5,1],[.25,.75],[.5,.5],[.75,.75]],
    8: [[.5,1],[.75,.75],[1,1]],
    9: [[.75,.75],[1,1],[1,.5]],
    10:[[.75,.75],[1,.5],[.75,.25],[.5,.5]],
    11:[[1,.5],[.75,.25],[1,0]],
    12:[[.75,.25],[1,0],[.5,0]],
}
_PLANET_ORDER = ['Lagna','Sun','Moon','Mars','Mercury','Jupiter',
                 'Venus','Saturn','Rahu','Ketu','Maandi','Gulika','Bhava Lagna']


def _fmt_lon(lon):
    if lon is None: return ''
    sign_n = int(lon / 30) % 12
    d_in_s = lon % 30
    d = int(d_in_s)
    m_d = (d_in_s - d) * 60
    m = int(m_d)
    s = (m_d - m) * 60
    return f'{d} {_SIGN_ABBS[sign_n]} {m:02d}\' {s:05.2f}"'


def _build_ni_svg(planets_data, lagna_sign, size=270):
    S = size
    lagna_num = _SIGN_NUM.get(lagna_sign, 1)

    house_bodies = {h: [] for h in range(1, 13)}
    for body, pdata in planets_data.items():
        sign = pdata.get('sign', '')
        snum = _SIGN_NUM.get(sign)
        if not snum: continue
        house = ((snum - lagna_num) % 12) + 1
        abbr  = _PABBR.get(body, body[:2])
        if pdata.get('retrograde'): abbr += 'ᴿ'
        house_bodies[house].append((body, abbr))

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {S} {S}" width="{S}" height="{S}" style="display:block">']
    parts.append(f'<rect width="{S}" height="{S}" fill="#f8f9fb"/>')

    for house, poly in _NI_POLYS.items():
        pts = ' '.join(f'{x*S:.1f},{y*S:.1f}' for x, y in poly)
        cx  = sum(p[0] for p in poly) / len(poly) * S
        cy  = sum(p[1] for p in poly) / len(poly) * S

        parts.append(f'<polygon points="{pts}" fill="#fff" stroke="#94a3b8" stroke-width="1.2"/>')

        # sign label: top of cell (min y), matching hora-prakash style
        sign_idx  = (lagna_num + house - 2) % 12
        sign_abbr = _SIGN_ABBS[sign_idx]
        sign_num  = sign_idx + 1
        min_y = min(p[1] for p in poly) * S
        max_y = max(p[1] for p in poly) * S
        cell_h = max_y - min_y
        sign_font = 11
        sign_y = min_y + cell_h * 0.22 + sign_font
        parts.append(
            f'<text x="{cx:.1f}" y="{sign_y:.1f}" text-anchor="middle" '
            f'font-size="{sign_font}" font-weight="700" fill="#475569" font-family="system-ui,sans-serif">'
            f'{sign_num}</text>'
        )

        bodies = house_bodies[house]
        n = len(bodies)
        line_h = min(14, max(11, int((max_y - sign_y - 6) / max(n, 1))))
        for i, (body, abbr) in enumerate(bodies):
            color  = _PCOLOR.get(body, '#374151')
            weight = 'bold' if body == 'Lagna' else '500'
            py = sign_y + 6 + (i + 0.5) * line_h
            parts.append(f'<text x="{cx:.1f}" y="{py:.1f}" text-anchor="middle" '
                         f'font-size="11" fill="{color}" font-weight="{weight}" '
                         f'font-family="system-ui,sans-serif">{abbr}</text>')

    parts.append('</svg>')
    return ''.join(parts)


def _build_chart_view(core):
    planets = core.get('planets', {})
    birth   = core.get('birth', {})
    panch   = core.get('panchang', {})
    karakas = core.get('karakas', {})
    divs    = core.get('divisionals', {})
    dasha   = core.get('dasha', {})

    lagna_sign = planets.get('Lagna', {}).get('sign', 'Aries')
    d9_data    = next((v for k, v in divs.items() if 'D9' in k), {})
    d9_lagna   = d9_data.get('Lagna', {}).get('sign', 'Aries')
    d9_planets = {body: {'sign': pos.get('sign',''), 'retrograde': False}
                  for body, pos in d9_data.items() if pos.get('sign')}

    rasi_svg = _build_ni_svg(planets, lagna_sign)
    d9_svg   = _build_ni_svg(d9_planets, d9_lagna)

    karaka_rev = {planet: _KARAKA_ABB.get(full,'') for full, planet in karakas.items()}

    # Planet table rows
    rows = []
    for body in _PLANET_ORDER:
        p = planets.get(body)
        if not p: continue
        color   = _PCOLOR.get(body, '#1e293b')
        karaka  = karaka_rev.get(body, '')
        display = f'{body} - {karaka}' if karaka else body
        lon_str = _fmt_lon(p.get('longitude'))
        nak     = p.get('nakshatra', '')
        nak_a   = _NAK_ABB.get(nak, nak[:4] if nak else '')
        pada    = p.get('pada', '')
        rasi_a  = _SIGN_ABB.get(p.get('sign',''), '')
        nav_a   = _SIGN_ABB.get(d9_data.get(body, {}).get('sign',''), '')
        retro   = ' ᴿ' if p.get('retrograde') else ''
        rows.append(
            f'<tr><td style="color:{color};font-weight:600">{display}{retro}</td>'
            f'<td>{lon_str}</td><td>{nak_a}</td>'
            f'<td>{pada}</td><td>{rasi_a}</td><td>{nav_a}</td></tr>'
        )

    planet_table = (
        '<table class="jtable">'
        '<thead><tr><th>Body</th><th>Longitude</th>'
        '<th>Nakshatra</th><th>Pada</th><th>Rasi</th><th>Navamsa</th></tr></thead>'
        '<tbody>' + ''.join(rows) + '</tbody></table>'
    )

    # Birth info
    birth_rows = ''.join(
        f'<tr><td class="bi-key">{k.replace("_"," ").title()}</td>'
        f'<td class="bi-val">{v}</td></tr>'
        for k, v in birth.items() if v
    )

    # Panchang
    def _panch_txt(v):
        if isinstance(v, dict):
            name = v.get('name','')
            lord = v.get('lord','')
            rem  = v.get('remaining_pct','')
            txt  = f'{name} ({lord})' if lord else name
            return f'{txt} [{rem}% left]' if rem else txt
        return str(v) if v else ''

    panch_rows = ''.join(
        f'<tr><td class="bi-key">{k.replace("_"," ").title()}</td>'
        f'<td class="bi-val">{_panch_txt(v)}</td></tr>'
        for k, v in panch.items() if _panch_txt(v)
    )

    # Dasha — mahadasha + collapsible antardashas
    maha_list = list(dasha.items())
    dasha_lines = []
    for idx, (maha, mdata) in enumerate(maha_list):
        s = mdata.get('start', '')
        e = maha_list[idx+1][1].get('start','') if idx+1 < len(maha_list) else ''
        date_txt = f'{s} → {e}' if e else s
        antardashas = mdata.get('antardashas', {})
        antar_items = list(antardashas.items())
        antar_rows = ''.join(
            f'<tr><td class="ad-planet">{ap}</td><td class="ad-date">{adate}</td></tr>'
            for ap, adate in antar_items
        )
        dasha_lines.append(
            f'<details class="maha-row"><summary>'
            f'<span class="maha-planet">{maha}</span>'
            f'<span class="maha-date">{date_txt}</span>'
            f'</summary>'
            f'<table class="antar-table">{antar_rows}</table>'
            f'</details>'
        )
    dasha_rows = ''.join(dasha_lines)

    return f'''
<div class="astro-layout">
  <div class="chart-col">
    <div class="chart-card">
      <div class="chart-header">Natal Chart <span class="chart-tag">Rasi</span></div>
      {rasi_svg}
    </div>
    <div class="chart-card">
      <div class="chart-header">Natal Chart <span class="chart-tag">D-9</span></div>
      {d9_svg}
    </div>
  </div>
  <div class="info-col">
    <div class="table-card">{planet_table}</div>
    <div class="info-row">
      <div class="info-card">
        <div class="info-title">Birth Details</div>
        <table class="itable"><tbody>{birth_rows}</tbody></table>
        <div class="info-title" style="margin-top:.1rem">Panchang</div>
        <table class="itable"><tbody>{panch_rows}</tbody></table>
      </div>
      <div class="info-card">
        <div class="info-title">Vimshottari Dasha</div>
        <div class="dasha-list">{dasha_rows}</div>
      </div>
    </div>
  </div>
</div>'''

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
EXTRACT_SH  = os.path.join(SCRIPTS_DIR, 'jhora_extract.sh')
OUT_DIR     = os.path.join(SCRIPTS_DIR, 'jhora_data')
PORT        = 8080
PLACES_JSON = os.path.join(os.path.dirname(SCRIPTS_DIR), 'public', 'places.json')

# ── HTML ──────────────────────────────────────────────────────────────────────

def form_html(error='', charts=None):
    now   = datetime.now()
    today = now.strftime('%Y-%m-%d')
    time_ = now.strftime('%H:%M')
    err   = f'<p class="error">{error}</p>' if error else ''

    # Saved charts list
    if charts is None:
        charts = _list_charts()
    if charts:
        chart_items = ''.join(
            f'<div class="chart-item">'
            f'<a class="ci-name" href="/view/{c["id"]}">{c["name"]}</a>'
            f'<div class="ci-meta">'
            f'{c["extracted_at"][:10]}'
            f' &nbsp;·&nbsp; <a class="ci-runs" href="/view/{c["id"]}/runs">{c["runs"]} run{"s" if c["runs"]!=1 else ""}</a>'
            f'</div>'
            f'</div>'
            for c in charts
        )
        saved_section = f'<div class="saved-card"><div class="saved-title">Saved Charts</div>{chart_items}</div>'
    else:
        saved_section = ''

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>JHora Extractor</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: system-ui, sans-serif; background: #f4f6fb; color: #1e293b; padding: 2rem; }}
    h1 {{ font-size: 1.4rem; margin-bottom: 1.5rem; color: #4f46e5; }}
    .layout {{ display: flex; gap: 1.5rem; align-items: flex-start; flex-wrap: wrap; }}
    .card {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 12px;
             box-shadow: 0 1px 4px rgba(0,0,0,.06); padding: 1.5rem; width: 480px; }}
    label {{ display: block; font-size: .78rem; font-weight: 600; text-transform: uppercase;
             letter-spacing: .05em; color: #64748b; margin-bottom: .3rem; margin-top: 1rem; }}
    label:first-of-type {{ margin-top: 0; }}
    input {{ width: 100%; padding: .55rem .75rem; border: 1px solid #e2e8f0;
             border-radius: 8px; font-size: .9rem; color: #1e293b; }}
    input:focus {{ outline: none; border-color: #4f46e5; box-shadow: 0 0 0 3px rgba(79,70,229,.15); }}
    .row {{ display: grid; grid-template-columns: 1fr 1fr; gap: .75rem; }}
    button {{ margin-top: 1.5rem; width: 100%; padding: .7rem; background: #4f46e5;
              color: #fff; border: none; border-radius: 8px; font-size: 1rem;
              font-weight: 600; cursor: pointer; transition: background .15s; }}
    button:hover {{ background: #4338ca; }}
    button:disabled {{ background: #a5b4fc; cursor: not-allowed; }}
    .error {{ color: #ef4444; font-size: .85rem; margin-top: 1rem; }}
    /* Saved charts */
    .saved-card {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 12px;
                   box-shadow: 0 1px 4px rgba(0,0,0,.06); min-width: 240px; overflow: hidden; }}
    .saved-title {{ padding: .6rem 1rem; font-size: .7rem; font-weight: 700;
                    text-transform: uppercase; letter-spacing: .06em; color: #64748b;
                    background: #f8fafc; border-bottom: 1px solid #e2e8f0; }}
    .chart-item {{ display: flex; flex-direction: column; padding: .6rem 1rem;
                   border-bottom: 1px solid #f1f5f9; transition: background .1s; }}
    .chart-item:last-child {{ border-bottom: none; }}
    .chart-item:hover {{ background: #f0f4ff; }}
    .ci-name {{ font-weight: 600; font-size: .88rem; color: #4f46e5; text-decoration: none; }}
    .ci-name:hover {{ text-decoration: underline; }}
    .ci-meta {{ font-size: .72rem; color: #94a3b8; margin-top: .1rem; }}
    .ci-runs {{ color: #64748b; text-decoration: none; font-weight: 600; }}
    .ci-runs:hover {{ color: #4f46e5; text-decoration: underline; }}
    /* Place search */
    .place-wrap {{ position: relative; }}
    #place-search {{ width: 100%; padding: .55rem .75rem; border: 1px solid #e2e8f0;
                     border-radius: 8px; font-size: .9rem; color: #1e293b; }}
    #place-search:focus {{ outline: none; border-color: #4f46e5; box-shadow: 0 0 0 3px rgba(79,70,229,.15); }}
    #place-results {{ position: absolute; top: 100%; left: 0; right: 0; z-index: 50;
                      background: #fff; border: 1px solid #e2e8f0; border-radius: 8px;
                      box-shadow: 0 4px 16px rgba(0,0,0,.1); max-height: 220px;
                      overflow-y: auto; display: none; }}
    #place-results.open {{ display: block; }}
    .pr-item {{ padding: .45rem .75rem; cursor: pointer; font-size: .85rem;
                border-bottom: 1px solid #f1f5f9; color: #1e293b; }}
    .pr-item:last-child {{ border-bottom: none; }}
    .pr-item:hover, .pr-item.active {{ background: #f0f4ff; color: #4f46e5; }}
    .pr-coords {{ font-size: .72rem; color: #94a3b8; margin-left: .4rem; }}
    /* Loader overlay */
    #loader {{ display: none; position: fixed; inset: 0; background: rgba(244,246,251,.85);
               z-index: 100; flex-direction: column; align-items: center; justify-content: center; gap: 1rem; }}
    #loader.active {{ display: flex; }}
    .spinner {{ width: 48px; height: 48px; border: 4px solid #e2e8f0;
                border-top-color: #4f46e5; border-radius: 50%; animation: spin .8s linear infinite; }}
    @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
    .loader-text {{ color: #4f46e5; font-weight: 600; font-size: 1rem; }}
    .loader-sub  {{ color: #64748b; font-size: .82rem; }}
  </style>
</head>
<body>
  <div id="loader">
    <div class="spinner"></div>
    <div class="loader-text">Extracting chart data...</div>
    <div class="loader-sub">JHora is running — takes ~30s</div>
  </div>

  <h1>JHora Extractor</h1>
  <div class="layout">
    <div class="card">
      <form id="form" method="POST" action="/extract">
        <label>Name</label>
        <input name="name" value="Test Chart" required>

        <div class="row">
          <div>
            <label>Date</label>
            <input name="date" type="date" value="{today}" required>
          </div>
          <div>
            <label>Time</label>
            <input name="time" type="time" value="{time_}" required>
          </div>
        </div>

        <label>Place Search</label>
        <div class="place-wrap">
          <input id="place-search" type="text" placeholder="Type city name…" autocomplete="off">
          <div id="place-results"></div>
        </div>

        <div class="row" style="margin-top:.75rem">
          <div>
            <label>Latitude</label>
            <input name="lat" id="inp-lat" type="number" step="any" value="28.6667" required>
          </div>
          <div>
            <label>Longitude</label>
            <input name="lon" id="inp-lon" type="number" step="any" value="77.3611" required>
          </div>
        </div>

        <div class="row">
          <div>
            <label>Timezone (hours, +east)</label>
            <input name="tz" id="inp-tz" type="number" step="any" value="5.5" required>
          </div>
          <div>
            <label>Place</label>
            <input name="place" id="inp-place" value="New Delhi">
          </div>
        </div>

        {err}
        <button type="submit" id="btn">Extract Chart</button>
      </form>
    </div>
    {saved_section}
  </div>

  <script>
    document.getElementById('form').addEventListener('submit', () => {{
      document.getElementById('loader').classList.add('active');
      document.getElementById('btn').disabled = true;
    }});

    let PLACES = [];
    fetch('/places.json').then(r => r.json()).then(d => {{ PLACES = d; }});

    const searchEl     = document.getElementById('place-search');
    const resultsEl    = document.getElementById('place-results');
    let activeIdx      = -1;
    let currentMatches = [];

    function tzToFloat(z) {{
      const m = z.match(/([+-])(\\d{{2}}):(\\d{{2}})/);
      if (!m) return 0;
      return (parseInt(m[2]) + parseInt(m[3]) / 60) * (m[1] === '-' ? -1 : 1);
    }}

    function showResults(matches) {{
      activeIdx = -1;
      currentMatches = matches.slice(0, 40);
      while (resultsEl.firstChild) resultsEl.removeChild(resultsEl.firstChild);
      currentMatches.forEach((p, i) => {{
        const item   = document.createElement('div');
        item.className = 'pr-item';
        const name   = document.createElement('span');
        name.textContent = p.n;
        const coords = document.createElement('span');
        coords.className = 'pr-coords';
        coords.textContent = ' ' + p.a.toFixed(2) + '°N ' + p.o.toFixed(2) + '°E';
        item.appendChild(name);
        item.appendChild(coords);
        item.addEventListener('click', () => selectPlace(i));
        resultsEl.appendChild(item);
      }});
      resultsEl.classList.toggle('open', currentMatches.length > 0);
    }}

    function selectPlace(i) {{
      const p = currentMatches[i];
      if (!p) return;
      document.getElementById('inp-lat').value   = p.a;
      document.getElementById('inp-lon').value   = p.o;
      document.getElementById('inp-tz').value    = tzToFloat(p.z);
      document.getElementById('inp-place').value = p.n;
      searchEl.value = p.n;
      resultsEl.classList.remove('open');
    }}

    searchEl.addEventListener('input', () => {{
      const q = searchEl.value.trim().toLowerCase();
      if (q.length < 2) {{ resultsEl.classList.remove('open'); return; }}
      showResults(PLACES.filter(p => p.n.toLowerCase().includes(q)));
    }});

    searchEl.addEventListener('keydown', e => {{
      const items = resultsEl.querySelectorAll('.pr-item');
      if      (e.key === 'ArrowDown')               {{ activeIdx = Math.min(activeIdx + 1, items.length - 1); }}
      else if (e.key === 'ArrowUp')                 {{ activeIdx = Math.max(activeIdx - 1, 0); }}
      else if (e.key === 'Enter' && activeIdx >= 0) {{ e.preventDefault(); selectPlace(activeIdx); return; }}
      else if (e.key === 'Escape')                  {{ resultsEl.classList.remove('open'); return; }}
      items.forEach((el, i) => el.classList.toggle('active', i === activeIdx));
      if (items[activeIdx]) items[activeIdx].scrollIntoView({{ block: 'nearest' }});
    }});

    document.addEventListener('click', e => {{
      if (!e.target.closest('.place-wrap')) resultsEl.classList.remove('open');
    }});
  </script>
</body>
</html>"""


def result_html(raw, dev, llm, core):
    name    = core.get('meta', {}).get('name', raw.get('name', ''))
    ext_at  = core.get('meta', {}).get('extracted_at', raw.get('extracted_at', ''))
    n_plan  = len(core.get('planets', {}))
    n_divs  = len(core.get('divisionals', {}))
    n_av    = len(core.get('ashtakavarga', {}))
    n_chart = len(llm.get('charts', {}))

    raw_str  = json.dumps(raw,  indent=2)
    dev_str  = json.dumps(dev,  indent=2)
    llm_str  = json.dumps(llm,  indent=2)
    core_str = json.dumps(core, indent=2)

    chart_html = _build_chart_view(core)

    def tree_panel(key):
        return (
            f'<div class="tree-toolbar">'
            f'<input class="tree-search" id="search-{key}" placeholder="Search keys/values…" oninput="treeSearch(\'{key}\')">'
            f'<button class="tree-ctrl" onclick="treeExpandAll(\'{key}\')">Expand All</button>'
            f'<button class="tree-ctrl" onclick="treeCollapseAll(\'{key}\')">Collapse All</button>'
            f'</div>'
            f'<div class="tree-wrap" id="tree-{key}"></div>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{name}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: system-ui, sans-serif; background: #f4f6fb; color: #1e293b; padding: 1.25rem 1.5rem; }}
    h1 {{ font-size: 1.3rem; color: #4f46e5; margin-bottom: .2rem; }}
    .meta {{ font-size: .78rem; color: #94a3b8; margin-bottom: .9rem; }}
    .toolbar {{ display: flex; gap: .5rem; align-items: center; margin-bottom: .9rem; flex-wrap: wrap; }}
    .toolbar a {{ color: #4f46e5; font-size: .85rem; text-decoration: none; margin-right: auto; }}
    .toolbar a:hover {{ text-decoration: underline; }}
    .btn-group {{ display: flex; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; }}
    .view-btn {{ padding: .35rem .9rem; border: none; border-right: 1px solid #e2e8f0;
                 font-size: .8rem; cursor: pointer; background: #fff; color: #64748b; }}
    .view-btn:last-child {{ border-right: none; }}
    .view-btn.active {{ background: #4f46e5; color: #fff; font-weight: 600; }}
    .view-btn.active:first-child {{ border-radius: 7px 0 0 7px; }}
    .view-sep {{ width: 1px; background: #e2e8f0; align-self: stretch; margin: 0 .25rem; }}
    pre {{ background: #1e293b; color: #e2e8f0; padding: 1.5rem; border-radius: 12px;
           font-size: .78rem; overflow: auto; max-height: 80vh; line-height: 1.6; }}
    .panel {{ display: none; }}
    .panel.active {{ display: block; }}
    .format-label {{ font-size: .7rem; text-transform: uppercase; letter-spacing: .06em;
                     color: #94a3b8; margin-bottom: .4rem; }}
    /* ── Astro layout ── */
    .astro-layout {{ display: flex; gap: 1rem; align-items: flex-start; }}
    .chart-col {{ display: flex; flex-direction: column; gap: .75rem; flex-shrink: 0; }}
    .chart-card {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; overflow: hidden; }}
    .chart-header {{ display: flex; justify-content: space-between; align-items: center;
                     padding: .4rem .85rem; font-size: .88rem; font-weight: 700;
                     background: #f8fafc; border-bottom: 1px solid #e2e8f0; color: #374151; }}
    .chart-tag {{ font-size: .78rem; font-weight: 700; color: #4f46e5;
                  background: #e0e7ff; padding: .1rem .45rem; border-radius: 4px; letter-spacing: .03em; }}
    .info-col {{ flex: 1; display: flex; flex-direction: column; gap: .75rem; min-width: 0; overflow: hidden; }}
    .table-card {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 10px; overflow: hidden; }}
    .jtable {{ width: 100%; border-collapse: collapse; font-size: .92rem; }}
    .jtable thead th {{ background: #f8fafc; padding: .42rem .75rem; text-align: left;
                        font-size: .82rem; text-transform: uppercase; letter-spacing: .04em;
                        color: #64748b; border-bottom: 2px solid #e2e8f0; white-space: nowrap; }}
    .jtable tbody tr:hover {{ background: #f8fafc; }}
    .jtable td {{ padding: .32rem .75rem; border-bottom: 1px solid #f1f5f9;
                  white-space: nowrap; font-family: 'Menlo','Consolas',monospace; font-size: .9rem; }}
    .jtable td:first-child {{ font-family: system-ui, sans-serif; font-size: .92rem; }}
    .info-row {{ display: flex; gap: .75rem; }}
    .info-card {{ flex: 1; background: #fff; border: 1px solid #e2e8f0; border-radius: 10px;
                  overflow: hidden; min-width: 0; }}
    .info-title {{ padding: .4rem .85rem; font-size: .78rem; font-weight: 700;
                   text-transform: uppercase; letter-spacing: .06em; color: #64748b;
                   background: #f8fafc; border-bottom: 1px solid #e2e8f0; }}
    .itable {{ width: 100%; border-collapse: collapse; font-size: .9rem; }}
    .itable tr:hover {{ background: #f8fafc; }}
    .bi-key {{ padding: .28rem .75rem; color: #059669; font-weight: 600; white-space: nowrap;
               border-bottom: 1px solid #f1f5f9; width: 38%; vertical-align: top; }}
    .bi-val {{ padding: .28rem .75rem; color: #7c2d12; border-bottom: 1px solid #f1f5f9; }}
    /* ── Dasha ── */
    .dasha-list {{ font-size: .9rem; }}
    .maha-row {{ border-bottom: 1px solid #f1f5f9; }}
    .maha-row summary {{ display: flex; justify-content: space-between; align-items: center;
                         padding: .3rem .75rem; cursor: pointer; list-style: none; }}
    .maha-row summary::-webkit-details-marker {{ display: none; }}
    .maha-row summary:hover {{ background: #f8fafc; }}
    .maha-planet {{ color: #059669; font-weight: 600; min-width: 3.5rem; }}
    .maha-date {{ color: #64748b; font-size: .84rem; }}
    .antar-table {{ width: 100%; border-collapse: collapse; background: #f8fafc; }}
    .ad-planet {{ padding: .22rem .75rem .22rem 2.2rem; color: #7c2d12; font-size: .86rem; width: 38%; }}
    .ad-date {{ padding: .22rem .75rem; color: #64748b; font-size: .86rem; }}
    .antar-table tr:hover {{ background: #f1f5f9; }}
    /* ── Tree ── */
    .tree-wrap {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 12px;
                  padding: 1rem 1.25rem; max-height: 80vh; overflow: auto;
                  font-size: .82rem; line-height: 1.75; font-family: 'Menlo','Consolas',monospace; }}
    .tree-row {{ display: flex; align-items: baseline; gap: .25rem; padding: .05rem 0; }}
    .tree-node {{ padding-left: 1.4rem; border-left: 1px dashed #e2e8f0; margin-left: .4rem; }}
    .tree-toggle {{ cursor: pointer; user-select: none; display: inline-flex; align-items: center;
                    gap: .3rem; padding: .1rem .35rem; border-radius: 4px;
                    background: #f1f5f9; border: 1px solid #e2e8f0;
                    font-size: .75rem; font-weight: 600; color: #4f46e5;
                    transition: background .1s; white-space: nowrap; }}
    .tree-toggle:hover {{ background: #e0e7ff; }}
    .tree-toggle::before {{ content: '▸'; font-size: .65rem; display: inline-block; transition: transform .15s; }}
    .tree-toggle.open::before {{ transform: rotate(90deg); }}
    .tree-type {{ font-size: .68rem; color: #94a3b8; margin-left: .2rem; }}
    .tree-key-str {{ color: #7c3aed; font-weight: 600; }}
    .tree-str {{ color: #059669; }}
    .tree-num {{ color: #d97706; }}
    .tree-bool {{ color: #4f46e5; font-weight: 600; }}
    .tree-null {{ color: #94a3b8; font-style: italic; }}
    .hidden {{ display: none; }}
    .tree-toolbar {{ display: flex; gap: .5rem; margin-bottom: .6rem; align-items: center; }}
    .tree-ctrl {{ font-size: .75rem; padding: .2rem .6rem; border: 1px solid #e2e8f0;
                  border-radius: 6px; background: #f8fafc; cursor: pointer; color: #4f46e5; }}
    .tree-ctrl:hover {{ background: #e0e7ff; }}
    .tree-search {{ flex: 1; padding: .25rem .6rem; border: 1px solid #e2e8f0;
                    border-radius: 6px; font-size: .78rem; outline: none; }}
    .tree-search:focus {{ border-color: #4f46e5; box-shadow: 0 0 0 2px rgba(79,70,229,.12); }}
    .tree-match {{ background: #fef08a; border-radius: 2px; }}
  </style>
</head>
<body>
  <h1>{name}</h1>
  <p class="meta">Extracted: {ext_at} &nbsp;·&nbsp; {n_plan} planets &nbsp;·&nbsp; {n_divs} divisionals &nbsp;·&nbsp; {n_av} AV bodies &nbsp;·&nbsp; {n_chart} charts</p>

  <div class="toolbar">
    <a href="/">← New chart</a>
    <div class="btn-group">
      <button class="view-btn active" onclick="setView('chart')">Chart</button>
    </div>
    <div class="btn-group">
      <button class="view-btn" onclick="setView('raw')">Raw JSON</button>
      <button class="view-btn" onclick="setView('dev')">Dev JSON</button>
      <button class="view-btn" onclick="setView('llm')">LLM JSON</button>
      <button class="view-btn" onclick="setView('core')">Core JSON</button>
    </div>
    <div class="btn-group">
      <button class="view-btn" onclick="setView('raw-tree')">Raw Tree</button>
      <button class="view-btn" onclick="setView('dev-tree')">Dev Tree</button>
      <button class="view-btn" onclick="setView('llm-tree')">LLM Tree</button>
      <button class="view-btn" onclick="setView('core-tree')">Core Tree</button>
    </div>
  </div>

  <div id="panel-chart"    class="panel active">{chart_html}</div>
  <div id="panel-raw"      class="panel"><p class="format-label">Raw — original parsed output</p><pre id="pre-raw"></pre></div>
  <div id="panel-dev"      class="panel"><p class="format-label">Dev — clean, abbreviations kept</p><pre id="pre-dev"></pre></div>
  <div id="panel-llm"      class="panel"><p class="format-label">LLM — fully expanded + ASCII charts</p><pre id="pre-llm"></pre></div>
  <div id="panel-core"     class="panel"><p class="format-label">Core — 15 bodies, full names</p><pre id="pre-core"></pre></div>
  <div id="panel-raw-tree"  class="panel"><p class="format-label">Raw Tree</p>{tree_panel('raw')}</div>
  <div id="panel-dev-tree"  class="panel"><p class="format-label">Dev Tree</p>{tree_panel('dev')}</div>
  <div id="panel-llm-tree"  class="panel"><p class="format-label">LLM Tree</p>{tree_panel('llm')}</div>
  <div id="panel-core-tree" class="panel"><p class="format-label">Core Tree</p>{tree_panel('core')}</div>

  <script>
    const DATASETS = {{
      raw:  {raw_str},
      dev:  {dev_str},
      llm:  {llm_str},
      core: {core_str},
    }};

    document.getElementById('pre-raw').textContent  = JSON.stringify(DATASETS.raw,  null, 2);
    document.getElementById('pre-dev').textContent  = JSON.stringify(DATASETS.dev,  null, 2);
    document.getElementById('pre-llm').textContent  = JSON.stringify(DATASETS.llm,  null, 2);
    document.getElementById('pre-core').textContent = JSON.stringify(DATASETS.core, null, 2);

    // ── Tree builder ──────────────────────────────────────────────────────────
    function makeToggle(label, count, type) {{
      const tog = document.createElement('span');
      tog.className = 'tree-toggle';
      tog.dataset.label = label;
      const typeSpan = document.createElement('span');
      typeSpan.className = 'tree-type';
      typeSpan.textContent = type === 'array' ? `[${{count}}]` : `{{${{count}}}}`;
      tog.appendChild(document.createTextNode(label));
      tog.appendChild(typeSpan);
      return tog;
    }}

    function buildTree(val, container, depth) {{
      depth = depth || 0;
      if (Array.isArray(val)) {{
        const tog = makeToggle(`Array`, val.length, 'array');
        container.appendChild(tog);
        const inner = document.createElement('div');
        inner.className = 'tree-node' + (depth > 0 ? ' hidden' : '');
        val.forEach((v, i) => {{
          const row = document.createElement('div');
          row.className = 'tree-row';
          const key = document.createElement('span');
          key.className = 'tree-key'; key.textContent = i + ': ';
          row.appendChild(key); buildTree(v, row, depth + 1); inner.appendChild(row);
        }});
        container.appendChild(inner);
        tog.onclick = (e) => {{ e.stopPropagation(); tog.classList.toggle('open'); inner.classList.toggle('hidden'); }};
      }} else if (val !== null && typeof val === 'object') {{
        const keys = Object.keys(val);
        const tog = makeToggle(`Object`, keys.length, 'object');
        container.appendChild(tog);
        const inner = document.createElement('div');
        inner.className = 'tree-node' + (depth > 0 ? ' hidden' : '');
        keys.forEach(k => {{
          const row = document.createElement('div');
          row.className = 'tree-row';
          const key = document.createElement('span');
          key.className = 'tree-key-str';
          key.textContent = k + ': ';
          key.dataset.key = k;
          row.appendChild(key); buildTree(val[k], row, depth + 1); inner.appendChild(row);
        }});
        container.appendChild(inner);
        tog.onclick = (e) => {{ e.stopPropagation(); tog.classList.toggle('open'); inner.classList.toggle('hidden'); }};
      }} else {{
        const leaf = document.createElement('span');
        if (val === null)                {{ leaf.className='tree-null'; leaf.textContent='null'; }}
        else if (typeof val==='boolean') {{ leaf.className='tree-bool'; leaf.textContent=String(val); }}
        else if (typeof val==='number')  {{ leaf.className='tree-num';  leaf.textContent=val; }}
        else                             {{ leaf.className='tree-str';  leaf.textContent='"'+val+'"'; leaf.dataset.val=val; }}
        container.appendChild(leaf);
      }}
    }}

    // Build trees lazily on first switch
    const treeBuilt = {{}};
    function ensureTree(key) {{
      if (!treeBuilt[key]) {{
        buildTree(DATASETS[key], document.getElementById('tree-' + key), 0);
        treeBuilt[key] = true;
      }}
    }}

    // ── Expand / Collapse all ─────────────────────────────────────────────────
    function treeExpandAll(key) {{
      ensureTree(key);
      document.getElementById('tree-' + key).querySelectorAll('.tree-toggle').forEach(t => {{
        t.classList.add('open');
        t.nextElementSibling && t.nextElementSibling.classList.remove('hidden');
      }});
    }}
    function treeCollapseAll(key) {{
      ensureTree(key);
      document.getElementById('tree-' + key).querySelectorAll('.tree-toggle').forEach((t, i) => {{
        if (i === 0) return; // keep root open
        t.classList.remove('open');
        t.nextElementSibling && t.nextElementSibling.classList.add('hidden');
      }});
    }}

    // ── Search / highlight ────────────────────────────────────────────────────
    function clearHighlights(key) {{
      document.getElementById('tree-' + key).querySelectorAll('.tree-match').forEach(el => {{
        el.classList.remove('tree-match');
      }});
    }}
    function treeSearch(key) {{
      const q = document.getElementById('search-' + key).value.trim().toLowerCase();
      clearHighlights(key);
      if (!q) return;
      ensureTree(key);
      const wrap = document.getElementById('tree-' + key);
      // Expand all first so everything is visible
      wrap.querySelectorAll('.tree-toggle').forEach(t => {{
        t.classList.add('open');
        t.nextElementSibling && t.nextElementSibling.classList.remove('hidden');
      }});
      // Highlight matching keys and values
      wrap.querySelectorAll('[data-key],[data-val]').forEach(el => {{
        const txt = (el.dataset.key || el.dataset.val || '').toLowerCase();
        if (txt.includes(q)) el.classList.add('tree-match');
      }});
    }}

    const VIEWS = ['chart','raw','dev','llm','core','raw-tree','dev-tree','llm-tree','core-tree'];
    function setView(mode) {{
      VIEWS.forEach(v => {{
        document.getElementById('panel-' + v).classList.toggle('active', v === mode);
      }});
      document.querySelectorAll('.view-btn').forEach(btn => {{
        const matches = btn.textContent.trim().toLowerCase().replace(' ','') === mode.replace('-','');
        btn.classList.toggle('active', matches);
      }});
      if (mode.endsWith('-tree')) ensureTree(mode.slice(0, -5));
    }}
  </script>
</body>
</html>"""


# ── Shared helpers ────────────────────────────────────────────────────────────

def _latest_run_dir(name):
    safe     = re.sub(r'[^\w\-]', '_', name)
    name_dir = os.path.join(OUT_DIR, safe)
    if not os.path.isdir(name_dir): return None
    runs = sorted(os.listdir(name_dir))
    return os.path.join(name_dir, runs[-1]) if runs else None

def _load_format(run_dir, fmt='core'):
    fname = {'raw':'parsed.json','dev':'parsed_dev.json',
             'llm':'parsed_llm.json','core':'parsed_core.json'}.get(fmt, 'parsed_core.json')
    p = os.path.join(run_dir, fname)
    with open(p) as f: return json.load(f)

def _list_charts():
    if not os.path.isdir(OUT_DIR): return []
    charts = []
    for safe in sorted(os.listdir(OUT_DIR)):
        name_dir = os.path.join(OUT_DIR, safe)
        if not os.path.isdir(name_dir): continue
        runs = sorted(os.listdir(name_dir))
        if not runs: continue
        run_dir = os.path.join(name_dir, runs[-1])
        try:
            meta = _load_format(run_dir, 'core')['meta']
            charts.append({'name': meta['name'], 'extracted_at': meta['extracted_at'],
                           'runs': len(runs), 'id': safe})
        except Exception:
            pass
    return charts

def _list_runs(chart_id):
    """Return all runs for a chart_id, newest first, with metadata."""
    safe     = re.sub(r'[^\w\-]', '_', chart_id)
    name_dir = os.path.join(OUT_DIR, safe)
    if not os.path.isdir(name_dir): return []
    runs = []
    for ts in sorted(os.listdir(name_dir), reverse=True):
        run_dir = os.path.join(name_dir, ts)
        try:
            meta = _load_format(run_dir, 'core')['meta']
            runs.append({'ts': ts, 'extracted_at': meta['extracted_at'],
                         'name': meta['name'], 'run_dir': run_dir})
        except Exception:
            runs.append({'ts': ts, 'extracted_at': ts, 'name': chart_id, 'run_dir': run_dir})
    return runs

def runs_html(chart_id, runs):
    name = runs[0]['name'] if runs else chart_id
    items = ''.join(
        f'<a class="run-item" href="/view/{chart_id}/{r["ts"]}">'
        f'<span class="ri-ts">{r["extracted_at"]}</span>'
        f'</a>'
        for r in runs
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Runs — {name}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: system-ui, sans-serif; background: #f4f6fb; color: #1e293b; padding: 2rem; }}
    h1 {{ font-size: 1.3rem; color: #4f46e5; margin-bottom: .3rem; }}
    .sub {{ font-size: .82rem; color: #94a3b8; margin-bottom: 1.25rem; }}
    .back {{ font-size: .85rem; color: #4f46e5; text-decoration: none; display: inline-block; margin-bottom: 1rem; }}
    .back:hover {{ text-decoration: underline; }}
    .card {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 12px;
             overflow: hidden; max-width: 480px; }}
    .run-item {{ display: flex; align-items: center; padding: .65rem 1rem;
                 border-bottom: 1px solid #f1f5f9; text-decoration: none;
                 color: #1e293b; transition: background .1s; }}
    .run-item:last-child {{ border-bottom: none; }}
    .run-item:hover {{ background: #f0f4ff; }}
    .ri-ts {{ font-family: 'Menlo','Consolas',monospace; font-size: .82rem; color: #4f46e5; }}
  </style>
</head>
<body>
  <a class="back" href="/">← Home</a>
  <h1>{name}</h1>
  <p class="sub">{len(runs)} extraction run{"s" if len(runs)!=1 else ""}</p>
  <div class="card">{items}</div>
</body>
</html>"""

def _run_extraction(params):
    name  = params.get('name','').strip()
    date  = params.get('date','').strip()
    time_ = params.get('time','').strip()
    lat   = params.get('lat','').strip()
    lon   = params.get('lon','').strip()
    tz    = params.get('tz','').strip()
    place = params.get('place','Unknown').strip()
    if not all([name, date, time_, lat, lon, tz]):
        return None, 'Missing required fields: name, date, time, lat, lon, tz'
    cmd = ['bash', EXTRACT_SH,
           '--name', name, '--date', date, '--time', time_,
           '--lat', lat, '--lon', lon, '--tz', tz, '--place', place]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            return None, r.stderr.strip() or 'Extraction failed'
    except subprocess.TimeoutExpired:
        return None, 'Extraction timed out'
    run_dir = _latest_run_dir(name)
    if not run_dir: return None, 'Output not found after extraction'
    return run_dir, None


# ── Handler ───────────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        print(f"  {self.address_string()} {fmt % args}")

    def send_html(self, html, status=200):
        body = html.encode()
        self.send_response(status)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, data, status=200):
        body = json.dumps(data, indent=2).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def send_err(self, msg, status=400):
        self.send_json({'error': msg}, status)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path.rstrip('/')
        qs     = dict(parse_qsl(parsed.query))

        # ── UI ──
        if path == '':
            self.send_html(form_html()); return

        # ── View saved chart ──
        m = re.match(r'^/view/([^/]+)/runs$', path)
        if m:
            chart_id = m.group(1)
            runs = _list_runs(chart_id)
            if not runs: self.send_html(form_html(error=f'No runs for "{chart_id}"')); return
            self.send_html(runs_html(chart_id, runs)); return

        m = re.match(r'^/view/([^/]+)/([^/]+)$', path)
        if m:
            chart_id, ts = m.group(1), m.group(2)
            safe     = re.sub(r'[^\w\-]', '_', chart_id)
            run_dir  = os.path.join(OUT_DIR, safe, ts)
            if not os.path.isdir(run_dir): self.send_html(form_html(error=f'Run not found')); return
            try:
                raw  = _load_format(run_dir, 'raw')
                dev  = _load_format(run_dir, 'dev')
                llm  = _load_format(run_dir, 'llm')
                core = _load_format(run_dir, 'core')
                self.send_html(result_html(raw, dev, llm, core)); return
            except Exception as e:
                self.send_html(form_html(error=str(e))); return

        m = re.match(r'^/view/([^/]+)$', path)
        if m:
            chart_id = m.group(1)
            run_dir  = _latest_run_dir(chart_id) or _latest_run_dir(chart_id.replace('_',' '))
            if not run_dir: self.send_html(form_html(error=f'Chart "{chart_id}" not found')); return
            try:
                raw  = _load_format(run_dir, 'raw')
                dev  = _load_format(run_dir, 'dev')
                llm  = _load_format(run_dir, 'llm')
                core = _load_format(run_dir, 'core')
                self.send_html(result_html(raw, dev, llm, core)); return
            except Exception as e:
                self.send_html(form_html(error=str(e))); return

        # ── Places data ──
        if path == '/places.json':
            if os.path.isfile(PLACES_JSON):
                with open(PLACES_JSON, 'rb') as f: data = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', len(data))
                self.send_header('Cache-Control', 'public, max-age=86400')
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_err('places.json not found', 404)
            return

        # ── REST API ──
        if path == '/api/charts':
            self.send_json({'charts': _list_charts()}); return

        m = re.match(r'^/api/charts/([^/]+)$', path)
        if m:
            name    = m.group(1).replace('_', ' ')
            fmt     = qs.get('format', 'core')
            run_dir = _latest_run_dir(m.group(1)) or _latest_run_dir(name)
            if not run_dir: self.send_err('Chart not found', 404); return
            self.send_json(_load_format(run_dir, fmt)); return

        m = re.match(r'^/api/charts/([^/]+)/planets$', path)
        if m:
            name    = m.group(1).replace('_', ' ')
            fmt     = qs.get('format', 'core')
            run_dir = _latest_run_dir(m.group(1)) or _latest_run_dir(name)
            if not run_dir: self.send_err('Chart not found', 404); return
            data = _load_format(run_dir, fmt)
            self.send_json({'name': data.get('meta',{}).get('name'), 'planets': data.get('planets',{})}); return

        m = re.match(r'^/api/charts/([^/]+)/divisionals/([^/]+)$', path)
        if m:
            name      = m.group(1).replace('_', ' ')
            chart_key = m.group(2)
            fmt       = qs.get('format', 'core')
            run_dir   = _latest_run_dir(m.group(1)) or _latest_run_dir(name)
            if not run_dir: self.send_err('Chart not found', 404); return
            divs = _load_format(run_dir, fmt).get('divisionals', {})
            # match by key or partial name
            match = divs.get(chart_key) or next(
                (v for k, v in divs.items() if chart_key.upper() in k.upper()), None)
            if not match: self.send_err(f'Divisional {chart_key!r} not found', 404); return
            self.send_json({chart_key: match}); return

        m = re.match(r'^/api/charts/([^/]+)/panchang$', path)
        if m:
            name    = m.group(1).replace('_', ' ')
            run_dir = _latest_run_dir(m.group(1)) or _latest_run_dir(name)
            if not run_dir: self.send_err('Chart not found', 404); return
            data = _load_format(run_dir, 'core')
            self.send_json({'name': data.get('meta',{}).get('name'), 'panchang': data.get('panchang',{})}); return

        self.send_response(404); self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        path   = parsed.path.rstrip('/')
        length = int(self.headers.get('Content-Length', 0))
        body   = self.rfile.read(length).decode()
        ct     = self.headers.get('Content-Type', '')

        # parse body — JSON or form
        if 'application/json' in ct:
            try: params = json.loads(body)
            except Exception: self.send_err('Invalid JSON'); return
        else:
            params = {k: v[0] for k, v in parse_qs(body).items()}

        # ── REST: POST /api/extract ──
        if path == '/api/extract':
            fmt = params.pop('format', 'core')
            run_dir, err = _run_extraction(params)
            if err: self.send_err(err); return
            self.send_json(_load_format(run_dir, fmt)); return

        # ── UI: POST /extract ──
        if path == '/extract':
            name = params.get('name','').strip()
            if not all([name, params.get('date'), params.get('time'),
                        params.get('lat'), params.get('lon'), params.get('tz')]):
                self.send_html(form_html(error='All fields required.')); return
            run_dir, err = _run_extraction(params)
            if err: self.send_html(form_html(error=err)); return
            raw  = _load_format(run_dir, 'raw')
            dev  = _load_format(run_dir, 'dev')
            llm  = _load_format(run_dir, 'llm')
            core = _load_format(run_dir, 'core')
            self.send_html(result_html(raw, dev, llm, core)); return

        self.send_response(404); self.end_headers()


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    server = HTTPServer(('0.0.0.0', PORT), Handler)
    print(f"JHora server running → http://localhost:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
