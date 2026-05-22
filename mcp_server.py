#!/usr/bin/env python3
"""
JHora MCP server — stdio JSON-RPC 2.0 (Model Context Protocol)

Usage:
  python3 scripts/mcp_server.py

Add to Claude Desktop config (~/.claude/claude_desktop_config.json):
  {
    "mcpServers": {
      "jhora": {
        "command": "python3",
        "args": ["/absolute/path/to/scripts/mcp_server.py"]
      }
    }
  }
"""

import json, os, re, subprocess, sys

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
EXTRACT_SH  = os.path.join(SCRIPTS_DIR, 'jhora_extract.sh')
OUT_DIR     = os.path.join(SCRIPTS_DIR, 'jhora_data')

# ── Data helpers ──────────────────────────────────────────────────────────────

def _latest_run_dir(name):
    safe     = re.sub(r'[^\w\-]', '_', name)
    name_dir = os.path.join(OUT_DIR, safe)
    if not os.path.isdir(name_dir): return None
    runs = sorted(os.listdir(name_dir))
    return os.path.join(name_dir, runs[-1]) if runs else None

def _load_format(run_dir, fmt='core'):
    fname = {'raw':'parsed.json','dev':'parsed_dev.json',
             'llm':'parsed_llm.json','core':'parsed_core.json'}.get(fmt, 'parsed_core.json')
    with open(os.path.join(run_dir, fname)) as f:
        return json.load(f)

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
            charts.append({'id': safe, 'name': meta['name'],
                           'extracted_at': meta['extracted_at'], 'runs': len(runs)})
        except Exception:
            pass
    return charts

def _run_extraction(params):
    required = ['name','date','time','lat','lon','tz']
    missing  = [k for k in required if not str(params.get(k,'')).strip()]
    if missing:
        return None, f'Missing fields: {", ".join(missing)}'
    cmd = ['bash', EXTRACT_SH,
           '--name',  str(params['name']).strip(),
           '--date',  str(params['date']).strip(),
           '--time',  str(params['time']).strip(),
           '--lat',   str(params['lat']).strip(),
           '--lon',   str(params['lon']).strip(),
           '--tz',    str(params['tz']).strip(),
           '--place', str(params.get('place','Unknown')).strip()]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            return None, r.stderr.strip() or 'Extraction failed'
    except subprocess.TimeoutExpired:
        return None, 'Extraction timed out (120s)'
    run_dir = _latest_run_dir(str(params['name']).strip())
    return (run_dir, None) if run_dir else (None, 'Output not found after extraction')


# ── Tool definitions ──────────────────────────────────────────────────────────

TOOLS = [
    {
        'name': 'list_charts',
        'description': 'List all previously extracted Vedic astrology charts.',
        'inputSchema': {
            'type': 'object',
            'properties': {},
            'required': []
        }
    },
    {
        'name': 'get_chart',
        'description': (
            'Get full chart data for a person by name. '
            'Returns planets, divisionals, panchang, ashtakavarga, dasha, karakas. '
            'format: "core" (15 bodies, default), "dev" (all bodies, abbr), '
            '"llm" (fully expanded + ASCII charts), "raw" (raw parsed output).'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'name': {'type': 'string', 'description': 'Person name (must match extracted chart)'},
                'format': {'type': 'string', 'enum': ['core','dev','llm','raw'], 'default': 'core'}
            },
            'required': ['name']
        }
    },
    {
        'name': 'get_planets',
        'description': 'Get planetary positions for a chart — sign, degree, house, nakshatra, retrograde, combust.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'name':   {'type': 'string', 'description': 'Person name'},
                'format': {'type': 'string', 'enum': ['core','dev','llm','raw'], 'default': 'core'}
            },
            'required': ['name']
        }
    },
    {
        'name': 'get_divisional',
        'description': (
            'Get planetary positions in a specific divisional chart (e.g. D9, D10, D1). '
            'Returns all bodies in that chart with sign, degree, longitude.'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'name':  {'type': 'string', 'description': 'Person name'},
                'chart': {'type': 'string', 'description': 'Chart key, e.g. "D9", "D10", "D1"'},
                'format': {'type': 'string', 'enum': ['core','dev','llm','raw'], 'default': 'core'}
            },
            'required': ['name', 'chart']
        }
    },
    {
        'name': 'get_panchang',
        'description': 'Get Panchang details for a chart — tithi, vara, nakshatra, yoga, karana, sunrise, kalam timings.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'name': {'type': 'string', 'description': 'Person name'}
            },
            'required': ['name']
        }
    },
    {
        'name': 'get_dasha',
        'description': 'Get Vimshottari Dasha periods (3-level: mahadasha → antardasha → pratyantardasha) for a chart.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'name': {'type': 'string', 'description': 'Person name'}
            },
            'required': ['name']
        }
    },
    {
        'name': 'summarize_chart',
        'description': (
            'Get a plain-text LLM-friendly summary of a Vedic astrology chart. '
            'Returns structured prose covering birth details, lagna, planets, '
            'current dasha, panchang, and key divisionals — no JSON parsing needed. '
            'Ideal for asking follow-up questions or generating interpretations.'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'name': {'type': 'string', 'description': 'Person name'},
                'include_divisionals': {
                    'type': 'boolean',
                    'description': 'Include D9/D10 divisional placements (default true)',
                    'default': True
                }
            },
            'required': ['name']
        }
    },
    {
        'name': 'extract_chart',
        'description': (
            'Extract a new Vedic astrology chart by running JHora. '
            'Requires JHora installed via Wine. Takes ~30 seconds. '
            'Returns the extracted chart data in core format.'
        ),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'name':  {'type': 'string', 'description': 'Person name'},
                'date':  {'type': 'string', 'description': 'Birth date YYYY-MM-DD'},
                'time':  {'type': 'string', 'description': 'Birth time HH:MM'},
                'lat':   {'type': 'number', 'description': 'Latitude (positive=north)'},
                'lon':   {'type': 'number', 'description': 'Longitude (positive=east)'},
                'tz':    {'type': 'number', 'description': 'Timezone offset in hours (e.g. 5.5 for IST)'},
                'place': {'type': 'string', 'description': 'Place name (optional, for reference)'}
            },
            'required': ['name','date','time','lat','lon','tz']
        }
    }
]


# ── Text summary ─────────────────────────────────────────────────────────────

def _fmt_planet(name, p):
    parts = [f"{p.get('sign','')} {p.get('sign_degree','')}"]
    if p.get('house'): parts.append(f"house {p['house']}")
    if p.get('nakshatra'): parts.append(f"nakshatra {p['nakshatra']} (lord: {p.get('nakshatra_lord','')})")
    if p.get('retrograde'): parts.append('retrograde')
    if p.get('combust'): parts.append('combust')
    return f"  {name:15s} {', '.join(parts)}"

def _fmt_dasha(dasha):
    lines = []
    for maha, mdata in list(dasha.items())[:3]:
        start = mdata.get('start',''); end = mdata.get('end','')
        lines.append(f"  {maha} ({start}–{end})")
        for antar, adata in list(mdata.get('antardashas',{}).items())[:3]:
            astart = adata.get('start',''); aend = adata.get('end','')
            lines.append(f"    └─ {antar} ({astart}–{aend})")
    return '\n'.join(lines)

def _build_summary(data, include_divisionals=True):
    meta    = data.get('meta', {})
    birth   = data.get('birth', {})
    panchang= data.get('panchang', {})
    planets = data.get('planets', {})
    karakas = data.get('karakas', {})
    dasha   = data.get('dasha', {})
    divs    = data.get('divisionals', {})

    lines = []

    # Header
    lines.append(f"=== VEDIC ASTROLOGY CHART: {meta.get('name','')} ===")
    lines.append(f"Extracted: {meta.get('extracted_at','')}")
    lines.append('')

    # Birth details
    lines.append('── BIRTH DETAILS ──')
    for k, v in birth.items():
        if v: lines.append(f"  {k.replace('_',' ').title():20s} {v}")
    lines.append('')

    # Panchang
    lines.append('── PANCHANG ──')
    for k, v in panchang.items():
        if isinstance(v, dict):
            lord = v.get('lord',''); rem = v.get('remaining_pct','')
            lines.append(f"  {k.replace('_',' ').title():20s} {v.get('name','')} (lord: {lord}, {rem}% left)")
        else:
            lines.append(f"  {k.replace('_',' ').title():20s} {v}")
    lines.append('')

    # Planets
    lines.append('── PLANETARY POSITIONS (Lagna + 9 Grahas + Upagrahas) ──')
    for name, p in planets.items():
        lines.append(_fmt_planet(name, p))
    lines.append('')

    # Karakas
    if karakas:
        lines.append('── KARAKAS ──')
        for k, v in karakas.items():
            lines.append(f"  {k:25s} {v}")
        lines.append('')

    # Dasha
    if dasha:
        lines.append('── VIMSHOTTARI DASHA (current + upcoming) ──')
        lines.append(_fmt_dasha(dasha))
        lines.append('')

    # Divisionals
    if include_divisionals:
        for chart_key in ['D1 (Rasi)','D9 (Navamsa)','D10 (Dasamsa)']:
            # match flexibly
            match = next((v for k, v in divs.items() if chart_key.split()[0] in k), None)
            if not match: match = divs.get(chart_key)
            if match:
                lines.append(f'── {chart_key} POSITIONS ──')
                for body, pos in match.items():
                    sign = pos.get('sign',''); deg = pos.get('degree','')
                    lines.append(f"  {body:15s} {sign} {deg}")
                lines.append('')

    return '\n'.join(lines)


# ── Tool dispatch ─────────────────────────────────────────────────────────────

def call_tool(name, args):
    if name == 'list_charts':
        charts = _list_charts()
        return {'charts': charts, 'count': len(charts)}

    if name == 'get_chart':
        person  = args.get('name','')
        fmt     = args.get('format', 'core')
        run_dir = _latest_run_dir(person)
        if not run_dir:
            raise ValueError(f'No chart found for "{person}". Use list_charts to see available charts.')
        return _load_format(run_dir, fmt)

    if name == 'get_planets':
        person  = args.get('name','')
        fmt     = args.get('format', 'core')
        run_dir = _latest_run_dir(person)
        if not run_dir:
            raise ValueError(f'No chart found for "{person}".')
        data = _load_format(run_dir, fmt)
        return {'name': data.get('meta',{}).get('name'), 'planets': data.get('planets',{})}

    if name == 'get_divisional':
        person    = args.get('name','')
        chart_key = args.get('chart','').upper()
        fmt       = args.get('format', 'core')
        run_dir   = _latest_run_dir(person)
        if not run_dir:
            raise ValueError(f'No chart found for "{person}".')
        divs = _load_format(run_dir, fmt).get('divisionals', {})
        match = divs.get(chart_key) or next(
            (v for k, v in divs.items() if chart_key in k.upper()), None)
        if not match:
            available = list(divs.keys())
            raise ValueError(f'Divisional {chart_key!r} not found. Available: {available}')
        return {chart_key: match}

    if name == 'get_panchang':
        person  = args.get('name','')
        run_dir = _latest_run_dir(person)
        if not run_dir:
            raise ValueError(f'No chart found for "{person}".')
        data = _load_format(run_dir, 'core')
        return {'name': data.get('meta',{}).get('name'), 'panchang': data.get('panchang',{})}

    if name == 'get_dasha':
        person  = args.get('name','')
        run_dir = _latest_run_dir(person)
        if not run_dir:
            raise ValueError(f'No chart found for "{person}".')
        data = _load_format(run_dir, 'core')
        return {'name': data.get('meta',{}).get('name'), 'dasha': data.get('dasha',{})}

    if name == 'summarize_chart':
        person  = args.get('name','')
        inc_div = args.get('include_divisionals', True)
        run_dir = _latest_run_dir(person)
        if not run_dir:
            raise ValueError(f'No chart found for "{person}". Use list_charts.')
        data = _load_format(run_dir, 'core')
        return _build_summary(data, include_divisionals=inc_div)

    if name == 'extract_chart':
        params  = {k: str(v) for k, v in args.items()}
        run_dir, err = _run_extraction(params)
        if err:
            raise RuntimeError(f'Extraction failed: {err}')
        return _load_format(run_dir, 'core')

    raise ValueError(f'Unknown tool: {name}')


# ── MCP protocol ──────────────────────────────────────────────────────────────

def send(obj):
    line = json.dumps(obj, ensure_ascii=False)
    sys.stdout.write(line + '\n')
    sys.stdout.flush()

def handle(msg):
    method  = msg.get('method','')
    msg_id  = msg.get('id')
    params  = msg.get('params', {})

    if method == 'initialize':
        send({'jsonrpc':'2.0','id':msg_id,'result':{
            'protocolVersion': '2024-11-05',
            'capabilities': {'tools': {}},
            'serverInfo': {'name': 'jhora-mcp', 'version': '1.0.0'}
        }})

    elif method == 'notifications/initialized':
        pass  # no response for notifications

    elif method == 'tools/list':
        send({'jsonrpc':'2.0','id':msg_id,'result':{'tools': TOOLS}})

    elif method == 'tools/call':
        tool_name = params.get('name','')
        tool_args = params.get('arguments', {})
        try:
            result = call_tool(tool_name, tool_args)
            text = result if isinstance(result, str) else json.dumps(result, indent=2)
            send({'jsonrpc':'2.0','id':msg_id,'result':{
                'content': [{'type':'text','text': text}],
                'isError': False
            }})
        except Exception as e:
            send({'jsonrpc':'2.0','id':msg_id,'result':{
                'content': [{'type':'text','text': str(e)}],
                'isError': True
            }})

    elif msg_id is not None:
        send({'jsonrpc':'2.0','id':msg_id,'error':{
            'code': -32601, 'message': f'Method not found: {method}'
        }})


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line: continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        handle(msg)


if __name__ == '__main__':
    main()
