# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Francesco Fullone
"""Cross-check the .pst reader of index.html against libpff (pypff).

  pip install libpff-python playwright && playwright install chromium
  python3 tests/pstcheck.py file.pst [more.pst ...]

For every message libpff finds, the folder, subject, number of recipients,
body and every attachment (size and SHA-256) must match what Nightglass shows
when the file is opened as a folder. Exit code 1 on any difference.
"""
import asyncio, hashlib, json, pathlib, sys, collections
import pypff
from playwright.async_api import async_playwright

URL = (pathlib.Path(__file__).resolve().parent.parent / 'index.html').as_uri()

WALK = r'''async ([url]) => {
 const u = new Uint8Array(await (await fetch(url)).arrayBuffer());
 const t0 = performance.now(); const a = pstArc('/x.pst', u, 0), A = arcFS(a), t1 = performance.now();
 const hex = async b => [...new Uint8Array(await crypto.subtle.digest('SHA-256', b))].map(x => x.toString(16).padStart(2, '0')).join('');
 const out = {what: a.what, open_ms: t1 - t0, folders: {}, msgs: []};
 const dec = new TextDecoder();
 const msg = async (dir, folder) => {
  const l = await A.list(dir), m = {folder, atts: [], emb: 0};
  const txt = dec.decode(await A.readBytes(dir + '/message.txt'));
  const hd = txt.split('\n\n')[0], f = k => ((hd.match(new RegExp('^' + k + ':\\s+(.*)$', 'm')) || [])[1] || '');
  m.subject = f('Subject'); m.from = f('From'); m.to = f('To'); m.cc = f('Cc'); m.body = txt.slice(hd.length + 2);
  m.error = txt.startsWith('Cannot read this message');
  for (const e of l) {
   if (e.dir) { m.emb++; continue }
   if (['message.txt', 'message.html', 'message.rtf', 'headers.txt'].includes(e.name)) { m[e.name] = e.size; continue }
   const b = await A.readBytes(e.path); m.atts.push({name: e.name, size: b.length, sha: await hex(b)});
  }
  out.msgs.push(m);
 };
 const walk = async (dir, rel) => {
  const l = await A.list(dir); let n = 0;
  for (const e of l) { if (!e.dir) continue; const r = rel ? rel + '/' + e.name : e.name;
   if (/^\d{4,} (\d{4}-\d\d-\d\d|-{10}) /.test(e.name)) { n++; await msg(e.path, rel) } else await walk(e.path, r) }
  out.folders[rel] = n;
 };
 await walk('/x.pst', ''); out.total_ms = performance.now() - t0; return out;
}'''

def pff_messages(path):
    f = pypff.file(); f.open(path); out = []
    root = f.get_root_folder()
    def top():
        # the IPM subtree ("Top of Personal Folders") is what Nightglass shows
        for i in range(root.number_of_sub_folders):
            s = root.get_sub_folder(i)
            if (s.name or '').lower() in ('top of personal folders', 'top of outlook data file', 'top of information store') or s.number_of_sub_folders > 3:
                return s
        return root
    def walk(fo, rel):
        for i in range(fo.number_of_sub_messages):
            m = fo.get_sub_message(i); atts = []; emb = 0
            for k in range(m.number_of_attachments):
                a = m.get_attachment(k); meth = None; has_data = False
                for e in a.get_record_set(0).entries:
                    if e.entry_type == 0x3705: meth = e.data_as_integer
                    if e.entry_type == 0x3701: has_data = True
                if meth == 5: emb += 1  # embedded message
                elif has_data:
                    n = a.get_size(); atts.append(hashlib.sha256(a.read_buffer(n) if n else b'').hexdigest())
            try: nrec = m.number_of_recipients if hasattr(m, 'number_of_recipients') else None
            except Exception: nrec = None
            body = (m.plain_text_body or b'').decode('utf-8', 'replace')
            out.append({'folder': rel, 'subject': m.subject or '', 'atts': sorted(atts), 'emb': emb, 'body': body.strip()[:200]})
        for i in range(fo.number_of_sub_folders):
            s = fo.get_sub_folder(i); walk(s, (rel + '/' if rel else '') + (s.name or ''))
    walk(top(), ''); return out

def norm_folder(p):
    import re
    return re.sub(r' \(\d+\)$', '', p)

async def check(pg, path):
    data = open(path, 'rb').read()
    async def serve(route): await route.fulfill(body=data, headers={'Access-Control-Allow-Origin': '*', 'Content-Type': 'application/octet-stream'})
    await pg.route('http://pst.test/x', serve)
    try: ng = await pg.evaluate(WALK, ['http://pst.test/x'])
    except Exception as e: print(f'{path}: Nightglass refuses it: {str(e).splitlines()[0]}'); return False
    finally: await pg.unroute('http://pst.test/x')
    pf = pff_messages(path); fails = []
    print(f'{path}: Nightglass {ng["what"]}, opened in {ng["open_ms"]:.0f} ms, everything read in {ng["total_ms"]:.0f} ms; libpff {len(pf)} messages')
    key = lambda m: (norm_folder(m['folder']).replace('∕', '/'), m['subject'].replace('\x01', ''))
    want = collections.defaultdict(list); [want[key(m)].append(m) for m in pf]
    got = collections.defaultdict(list); [got[(norm_folder(m['folder']), m['subject'])].append(m) for m in ng['msgs']]
    if len(ng['msgs']) != len(pf): fails.append(f'message count: Nightglass {len(ng["msgs"])}, libpff {len(pf)}')
    errs = [m for m in ng['msgs'] if m['error']]
    if errs: fails.append(f'{len(errs)} messages could not be read, first: {errs[0]["body"][:200]}')
    for k, ws in want.items():
        gs = got.get(k) or got.get((k[0], k[1].strip()))
        if not gs: fails.append(f'missing in Nightglass: {k}'); continue
        if len(gs) != len(ws): fails.append(f'{k}: {len(gs)} in Nightglass, {len(ws)} in libpff'); continue
        wa = sorted(sorted(w['atts']) for w in ws); ga = sorted(sorted(a['sha'] for a in g['atts']) for g in gs)
        if wa != ga: fails.append(f'{k}: attachments differ: libpff {wa} Nightglass {ga}')
        if sorted(w['emb'] for w in ws) != sorted(g['emb'] for g in gs): fails.append(f'{k}: embedded messages differ')
        for w in ws:
            ws_ = lambda t: ' '.join(t.split())
            if w['body'] and not any(ws_(w['body'])[:40] in ws_(g['body']) for g in gs): fails.append(f'{k}: body differs: {w["body"][:40]!r}')
    for f in fails[:20]: print('  FAIL', f)
    if len(fails) > 20: print(f'  … {len(fails) - 20} more')
    if not fails: print(f'  ok: {len(pf)} messages, {sum(len(m["atts"]) for m in pf)} attachments match byte for byte')
    return not fails

async def main(paths):
    async with async_playwright() as p:
        b = await p.chromium.launch(); pg = await b.new_page(); errs = []
        pg.on('pageerror', lambda e: errs.append(str(e)))
        await pg.goto(URL); await pg.wait_for_timeout(800)
        ok = all([await check(pg, x) for x in paths])
        if errs: print('page errors:', errs); ok = False
        await b.close()
    sys.exit(0 if ok else 1)

if __name__ == '__main__':
    asyncio.run(main(sys.argv[1:]))
