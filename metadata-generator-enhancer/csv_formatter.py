#!/usr/bin/env python3
import csv, json, re, sys
from pathlib import Path

def parse_labels(v):
    if not v or not v.startswith('['): return []
    try:
        p = json.loads(v)
        if isinstance(p, list):
            r = []
            for i in p:
                if isinstance(i, dict) and 'label' in i:
                    r.append(str(i['label']))
                elif not isinstance(i, dict):
                    r.append(str(i))
            return r
    except: pass
    try:
        c = v[1:-1].strip()
        if not c: return []
        e_list = re.split(r'\}\s*,\s*\{', c)
        r = []
        for e in e_list:
            e = e.strip().strip('{}').strip()
            if not e: continue
            m = re.search(r'label\s*:\s*([^,}]+?)(?:,|$)', e)
            if m: r.append(m.group(1).strip().strip('"\''))
        return r
    except: return []

def format_cell(v, col):
    if not v or v in ('[]', '[""]', '[""""]'): return ''
    if v.startswith('"') and v.endswith('"'): v = v[1:-1]
    if v.startswith('[{') and 'label' in v:
        l = parse_labels(v)
        if l: return ' ; '.join(l)
    if v.startswith('[') and any(x in col.lower() for x in ['date','name','subject','geo']):
        l = parse_labels(v)
        if l: return ' ; '.join(l)
    if '|@|' in v: return ' ; '.join(p.strip().strip('"\'') for p in v.split('|@|') if p.strip())
    return v

def convert(inp, out):
    with open(inp, 'r', encoding='utf-8') as f:
        r = csv.DictReader(f)
        with open(out, 'w', encoding='utf-8', newline='') as o:
            w = csv.DictWriter(o, fieldnames=r.fieldnames)
            w.writeheader()
            for row in r:
                w.writerow({k: format_cell(v, k) if v else '' for k, v in row.items()})

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 csv_formatter.py <input.csv> [output.csv]")
        sys.exit(1)
    inp = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else inp.parent / f"{inp.stem}_formatted.csv"
    print(f"Converting {inp} -> {out}")
    convert(inp, out)
    print("Done!")
