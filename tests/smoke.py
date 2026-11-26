# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Francesco Fullone
"""Smoke test: demo drive + live disk (fake desktop API) + git + archives + ssh + mail.

Needs: Python 3, `pip install playwright`, `playwright install chromium`, git, tar.
Run from the repository root:  python3 tests/smoke.py
Screenshots go to tests/out/.
"""
import asyncio, hashlib, json, os, pathlib, shutil, subprocess, sys
from playwright.async_api import async_playwright
sys.path.insert(0, os.path.dirname(__file__))
import harness, mailfixtures

ROOT = pathlib.Path(__file__).resolve().parent.parent
URL = (ROOT / 'index.html').as_uri()
OUT = ROOT / 'tests' / 'out'

def fake_home():
    h = harness.FAKE_HOME
    shutil.rmtree(h, ignore_errors=True); shutil.rmtree(harness.FAKE_TRASH, ignore_errors=True)
    os.makedirs(h + '/Documents'); os.makedirs(h + '/proj')
    open(h + '/Documents/note.txt', 'w', newline='').write('ciao\r\nmondo\r\n')
    g = lambda *a: subprocess.run(['git', *a], cwd=h + '/proj', check=True, capture_output=True)
    g('init', '-q', '-b', 'main'); g('config', 'user.email', 't@t'); g('config', 'user.name', 'T')
    open(h + '/proj/app.py', 'w').write('print(1)\n'); g('add', '.'); g('commit', '-qm', 'init')
    g('checkout', '-qb', 'feature/x'); open(h + '/proj/app.py', 'w').write('print(2)\n'); g('commit', '-qam', 'x'); g('checkout', '-q', 'main')
    open(h + '/proj/app.py', 'a').write('# local change\n')
    mailfixtures.main(h + '/mail')

async def run():
    OUT.mkdir(exist_ok=True); fake_home(); fails = []
    def check(cond, msg):
        print(('ok   ' if cond else 'FAIL ') + msg)
        if not cond: fails.append(msg)
    async with async_playwright() as p:
        b = await p.chromium.launch()
        errs = []
        # demo drive
        pg = await b.new_page(viewport={'width': 1300, 'height': 800}); pg.on('pageerror', lambda e: errs.append(str(e)))
        await pg.goto(URL); await pg.wait_for_timeout(1200); k = pg.keyboard
        async def cmd(c, w=400):
            await k.type(c); await k.press('Enter'); await pg.wait_for_timeout(w)
        check('briefing.txt' in await pg.inner_text('#pL .rows'), 'demo: left panel lists /ops/nightglass')
        await cmd('ls -l /intel'); check('dossier.pdf' in await pg.inner_text('#con'), 'demo: ls in console')
        await cmd('tar -czf /t.tgz /ops', 800); await cmd('tar -tf /t.tgz'); check('ops/nightglass/briefing.txt' in await pg.inner_text('#con'), 'demo: tar create + list')
        await k.press('Control+o'); await cmd('cd /intel')
        rows = await pg.eval_on_selector_all('#pL .row', 'e=>e.map(x=>x.textContent)')
        await pg.click(f'#pL .row[data-i="{[i for i,r in enumerate(rows) if "dossier.pdf" in r][0]}"]'); await k.press('F3'); await pg.wait_for_timeout(1500)
        check(await pg.locator('#ovb canvas').count() > 0, 'demo: PDF preview renders'); await pg.screenshot(path=str(OUT / 'pdf.png')); await k.press('Escape')
        await k.press('F1'); await pg.wait_for_timeout(200); check('Indice' in await pg.inner_text('#mant'), 'demo: manual opens'); await k.press('Escape')
        # live disk
        lv = await b.new_page(viewport={'width': 1300, 'height': 800}); lv.on('pageerror', lambda e: errs.append(str(e)))
        await harness.attach(lv); await lv.goto(URL); await lv.wait_for_timeout(1500); k = lv.keyboard
        check('LIVE DISK' in await lv.inner_text('#mode'), 'live: mode switches to LIVE DISK')
        check((await lv.evaluate('window.__icon||""')).startswith('data:image/png'), 'live: dock icon set')
        await k.type('cd ~/proj'); await k.press('Enter'); await lv.wait_for_timeout(800)
        check('main' in await lv.inner_text('#pL .ttl') and 'Mapp.py' in (await lv.inner_text('#pL .rows')).replace('\n', ''), 'live: git branch and status marks')
        await k.press('Control+x'); await k.press('g'); await lv.wait_for_timeout(600)
        items = await lv.eval_on_selector_all('#dd [data-mi]', 'e=>e.map(x=>x.textContent)')
        await lv.click(f'#dd [data-mi="{[i for i,t in enumerate(items) if "feature/x" in t][0]}"]'); await lv.wait_for_timeout(300); await k.press('Enter'); await lv.wait_for_timeout(900)
        check('feature/x' in await lv.inner_text('#pL .ttl'), 'live: browse git branch read-only')
        await lv.screenshot(path=str(OUT / 'git.png'))
        # ssh: right panel on the fake server, upload a file
        srv = os.environ.get('NG_FAKE_SERVER', '/tmp/ng-fakeserver'); shutil.rmtree(srv, ignore_errors=True); os.makedirs(srv)
        await k.press('Control+x'); await k.press('g'); await lv.wait_for_timeout(500)
        await lv.click('#dd [data-mi="0"]'); await lv.wait_for_timeout(800)
        await k.type('cd ~/Documents'); await k.press('Enter'); await lv.wait_for_timeout(500)
        await k.press('Tab'); await k.press('Control+x'); await k.press('s'); await lv.wait_for_selector('#din'); await lv.fill('#din', 'dev@lab'); await k.press('Enter'); await lv.wait_for_timeout(1500)
        check('dev@lab:' + srv in await lv.inner_text('#pR .ttl'), 'ssh: panel connected to the fake server')
        await k.press('Tab'); rows = await lv.eval_on_selector_all('#pL .row', 'e=>e.map(x=>x.textContent)')
        await lv.click(f'#pL .row[data-i="{[i for i,r in enumerate(rows) if "note.txt" in r][0]}"]'); await k.press('F5'); await lv.wait_for_selector('#dw.on'); await lv.wait_for_timeout(100); await k.press('Enter'); await lv.wait_for_timeout(1500)
        check(os.path.exists(srv + '/note.txt') and open(srv + '/note.txt', newline='').read() == 'ciao\r\nmondo\r\n', 'ssh: F5 uploads a file byte for byte')
        # mail: .eml, .msg, .mbox as read-only folders
        exp = json.load(open(harness.FAKE_HOME + '/mail/expected.json')); sha = lambda f: hashlib.sha256(open(f, 'rb').read()).hexdigest()
        ml = await b.new_page(viewport={'width': 1300, 'height': 800}); ml.on('pageerror', lambda e: errs.append(str(e)))
        await harness.attach(ml); await ml.goto(URL); await ml.wait_for_timeout(1500); k = ml.keyboard
        async def rows(): return await ml.eval_on_selector_all('#pL .row', 'e=>e.map(x=>x.textContent)')
        async def pick(n): r = await rows(); await ml.click(f'#pL .row[data-i="{[i for i,t in enumerate(r) if n in t][0]}"]')
        async def go(n, w=800): await pick(n); await k.press('Enter'); await ml.wait_for_timeout(w)
        async def copy_out(n): await pick(n); await k.press('F5'); await ml.wait_for_selector('#dw.on'); await ml.wait_for_timeout(100); await k.press('Enter'); await ml.wait_for_timeout(900)
        os.makedirs(harness.FAKE_HOME + '/out'); await k.type('cd ~/mail'); await k.press('Enter'); await ml.wait_for_timeout(600)
        await k.press('Tab'); await k.type('cd ~/out'); await k.press('Enter'); await ml.wait_for_timeout(500); await k.press('Tab')
        await go('sample.eml'); t = '\n'.join(await rows())
        check('(mail, read-only)' in await ml.inner_text('#pL .ttl') and all(x in t for x in ['message.txt', 'message.html', 'Fattura €42.pdf', 'logo.png', 'Verbale della riunione.eml']), 'mail: .eml opens as a folder of body and attachments')
        await copy_out('Fattura €42.pdf'); check(os.path.exists(harness.FAKE_HOME + '/out/Fattura €42.pdf') and sha(harness.FAKE_HOME + '/out/Fattura €42.pdf') == exp['pdf'], 'mail: F5 copies an .eml attachment out byte for byte')
        await pick('message.txt'); await k.press('F7'); await ml.wait_for_timeout(400); check('read-only' in (await ml.inner_text('#dw')).lower(), 'mail: writing inside a mail file is refused'); await k.press('Escape'); await ml.wait_for_timeout(200)
        await go('Verbale della riunione.eml'); check('Verbale della riunione.eml' in await ml.inner_text('#pL .ttl') and 'message.txt' in '\n'.join(await rows()), 'mail: a forwarded .eml inside opens too')
        await go('..'); await go('..'); check('~/mail' in await ml.inner_text('#pL .ttl'), 'mail: .. leaves nested mail files back to the disk')
        await go('sample.msg'); t = '\n'.join(await rows())
        check(all(x in t for x in ['report Q3 €.pdf', 'logo.png', 'message.rtf', 'Café alle 11 (message)']), 'mail: Outlook .msg opens with attachments, RTF and embedded message')
        await copy_out('report Q3 €.pdf'); check(sha(harness.FAKE_HOME + '/out/report Q3 €.pdf') == exp['pdf'], 'mail: F5 copies a .msg attachment out byte for byte')
        await pick('message.txt'); await k.press('F3'); await ml.wait_for_timeout(600); v = await ml.inner_text('#ovb')
        check('Giulia Verdi <giulia@example.com>' in v and 'Paolo Neri' in v and 'il report è pronto' in v, 'mail: .msg sender, recipients and body decoded'); await k.press('Escape'); await ml.wait_for_timeout(200)
        await go('..'); await go('inbox.mbox'); t = '\n'.join(await rows())
        check('0001 2026-11-20 Riunione di lunedì' in t and '0002 2026-11-02 Offre spéciale' in t and '0003' in t, 'mail: .mbox lists one folder per message')
        await go('0002'); await pick('message.txt'); await k.press('F3'); await ml.wait_for_timeout(600); v = await ml.inner_text('#ovb')
        check('Prix réduits.\nFrom now on' in v, 'mail: mbox message with base64 latin-1 body and >From unescaped'); await k.press('Escape'); await ml.wait_for_timeout(200)
        await go('..'); await go('..'); await pick('sample.eml'); await k.press('F3'); await ml.wait_for_timeout(1200)
        src = await ml.eval_on_selector('#ovb iframe', 'f=>f.srcdoc')
        check("default-src 'none'" in src and 'data:image/png;base64,' in src and 'remote images are not loaded' in await ml.inner_text('#ovb'), 'mail: F3 preview shows HTML with inline images, remote loads blocked')
        await ml.screenshot(path=str(OUT / 'mail.png')); await k.press('Escape'); await ml.wait_for_timeout(200)
        await pick('inbox.mbox'); await k.press('Control+x'); await k.press('u'); await ml.wait_for_selector('#dw.on'); await ml.wait_for_timeout(150); await k.press('Enter'); await ml.wait_for_timeout(1500)
        check(sha(harness.FAKE_HOME + '/out/inbox/0001 2026-11-20 Riunione di lunedì_ ordine del giorno ✓/Fattura €42.pdf') == exp['pdf'], 'mail: Ctrl-X u extracts a whole mailbox')
        # Outlook .pst: folders, messages, attachments, embedded message; "high" encoding split in small pieces; ANSI
        await go('sample.pst'); t = '\n'.join(await rows())
        check('(mail, read-only)' in await ml.inner_text('#pL .ttl') and all(x in t for x in ['Posta in arrivo', 'Posta inviata', 'Posta eliminata']), 'pst: .pst opens with its Outlook folders')
        await go('Posta in arrivo'); t = '\n'.join(await rows())
        check('Lavoro 2026' in t and '0001 2026-11-11 Pranzo 1' in t and '0004 2026-11-19 Report trimestrale Q3 — versione finale' in t, 'pst: a folder lists subfolders and messages by date')
        await go('0004'); t = '\n'.join(await rows())
        check(all(x in t for x in ['message.txt', 'message.html', 'message.rtf', 'headers.txt', 'Fattura PST €42.pdf', 'logo.png', 'Café alle 11 (message)']), 'pst: a message opens with body, attachments and embedded message')
        await copy_out('Fattura PST €42.pdf'); check(sha(harness.FAKE_HOME + '/out/Fattura PST €42.pdf') == exp['pdf'], 'pst: F5 copies a .pst attachment out byte for byte')
        await pick('message.txt'); await k.press('F3'); await ml.wait_for_timeout(600); v = await ml.inner_text('#ovb')
        check('Giulia Verdi <giulia@example.com>' in v and 'Paolo Neri' in v and 'il report è pronto' in v and '\x01' not in v, 'pst: sender, recipients and body decoded'); await k.press('Escape'); await ml.wait_for_timeout(200)
        await go('Café alle 11 (message)'); check('nota.txt' in '\n'.join(await rows()), 'pst: embedded message with its own attachment')
        for _ in range(4): await go('..', 500)
        await pick('sample.pst'); await k.press('F3'); await ml.wait_for_timeout(800); v = await ml.inner_text('#ovb')
        check('Outlook data file' in v and 'Posta in arrivo/Lavoro 2026' in v, 'pst: F3 on a .pst lists its folders'); await k.press('Escape'); await ml.wait_for_timeout(200)
        await pick('high-small.pst'); await k.press('Control+x'); await k.press('u'); await ml.wait_for_selector('#dw.on'); await ml.wait_for_timeout(150); await k.press('Enter'); await ml.wait_for_timeout(1500)
        hs = harness.FAKE_HOME + '/out/high-small/Posta in arrivo/'
        check(os.path.exists(hs + 'Lavoro 2026/0001 2026-11-11 Budget/message.txt') and sha(hs + '0004 2026-11-19 Report trimestrale Q3 — versione finale/Fattura PST €42.pdf') == exp['pdf'], 'pst: "high" encoding, every structure split in pieces, extracted with Ctrl-X u')
        await go('ansi.pst'); await go('Posta in arrivo'); await go('0004'); await pick('message.txt'); await k.press('F3'); await ml.wait_for_timeout(600); v = await ml.inner_text('#ovb')
        check('Report trimestrale Q3 - versione finale' in v and 'il report è pronto' in v, 'pst: ANSI .pst with Windows-1252 text'); await k.press('Escape'); await ml.wait_for_timeout(200)
        for _ in range(3): await go('..', 500)
        # Thunderbird folders: mbox files without extension
        async def pickx(n):
            r = await ml.eval_on_selector_all('#pL .row .c1', 'e=>e.map(x=>x.textContent.slice(1))'); await ml.click(f'#pL .row[data-i="{r.index(n)}"]')
        async def gox(n, w=800): await pickx(n); await k.press('Enter'); await ml.wait_for_timeout(w)
        await go('tb'); await go('Mail'); await go('Local Folders')
        await pickx('Trash'); await k.press('F3'); await ml.wait_for_timeout(600)
        check('1 message' in await ml.inner_text('#ovb'), 'thunderbird: F3 recognises a folder file without .msf'); await k.press('Escape'); await ml.wait_for_timeout(200)
        await gox('Inbox'); t = '\n'.join(await rows())
        check('(mail, read-only)' in await ml.inner_text('#pL .ttl') and '0001 2026-11-20 Benvenuto' in t and '0002 2026-11-22 Seconda' in t and 'Cancellato' not in t, 'thunderbird: Inbox next to Inbox.msf opens as a mailbox, expunged message hidden')
        await go('..'); await gox('Inbox.sbd'); await gox('Lavoro'); check('0001 2026-11-20 Progetto' in '\n'.join(await rows()), 'thunderbird: subfolder in Inbox.sbd')
        await go('..'); await go('..'); await gox('Trash'); check('0001 2026-11-20 Vecchio' in '\n'.join(await rows()), 'thunderbird: folder without .msf inside the profile')
        for _ in range(4): await go('..', 500)
        await gox('Posta'); check('0002 2026-11-21 Anche questa' in '\n'.join(await rows()), 'thunderbird: small mbox without extension outside a profile'); await go('..')
        opened = []; ml.on('console', lambda m: opened.append(m.text) if m.text.startswith('OPEN') else None)
        await gox('README'); check('~/mail' in await ml.inner_text('#pL .ttl') and any(x.endswith('/README') for x in opened), 'thunderbird: other files without extension still open in their app')
        # S3: fake aws on a local folder
        s3 = os.environ.setdefault('NG_FAKE_S3', '/tmp/ng-fakes3'); s3log = os.environ.setdefault('NG_FAKE_S3_LOG', '/tmp/ng-fakes3.log')
        shutil.rmtree(s3, ignore_errors=True); os.makedirs(s3 + '/logs/2024/08'); os.makedirs(s3 + '/logs/big')
        for d in range(1, 31): open(f'{s3}/logs/2024/08/app-{d:02d}.log', 'w').write(f'day {d}\n')
        for n in range(2500): open(f'{s3}/logs/big/obj-{n:05d}', 'w').close()
        open(s3log, 'w').close()
        os.makedirs(harness.FAKE_HOME + '/site/css'); open(harness.FAKE_HOME + '/site/index.html', 'w').write('<h1>x</h1>'); open(harness.FAKE_HOME + '/site/css/a.css', 'w').write('b{}')
        sp = await b.new_page(viewport={'width': 1300, 'height': 800}); sp.on('pageerror', lambda e: errs.append(str(e)))
        await harness.attach(sp); await sp.goto(URL); await sp.wait_for_timeout(1500); k = sp.keyboard
        async def srows(pn='pR'): return await sp.eval_on_selector_all(f'#{pn} .row', 'e=>e.map(x=>x.textContent)')
        async def spick(n, pn='pR'): r = await srows(pn); await sp.click(f'#{pn} .row[data-i="{[i for i,t in enumerate(r) if n in t][0]}"]')
        async def s3link(v, w=1500):
            await k.press('Control+x'); await k.press('3'); await sp.wait_for_selector('#din'); await sp.fill('#din', v); await k.press('Enter'); await sp.wait_for_timeout(w)
        async def dlg_ok(w=1500): await sp.wait_for_selector('#dw.on'); await sp.wait_for_timeout(150); await k.press('Enter'); await sp.wait_for_timeout(w)
        await k.type('cd ~'); await k.press('Enter'); await sp.wait_for_timeout(500); await k.press('Tab')
        await s3link('s3://logs/2024/08/')
        check('☁ s3://logs/2024/08' in await sp.inner_text('#pR .ttl') and len([r for r in await srows() if 'app-' in r]) == 30, 'S3: Ctrl-X 3 opens a prefix of a bucket in a panel')
        await spick('app-07.log'); await k.press('F5'); await dlg_ok()
        check(open(harness.FAKE_HOME + '/app-07.log').read() == 'day 7\n', 'S3: F5 downloads an object')
        await k.press('Tab'); await spick('Documents', 'pL'); await k.press('Enter'); await sp.wait_for_timeout(500); await spick('note.txt', 'pL'); await k.press('F5'); await dlg_ok()
        check(open(s3 + '/logs/2024/08/note.txt', newline='').read() == 'ciao\r\nmondo\r\n', 'S3: F5 uploads a file byte for byte')
        await spick('..', 'pL'); await k.press('Enter'); await sp.wait_for_timeout(400); await spick('site', 'pL'); await k.press('F5'); await dlg_ok(2000)
        check(open(s3 + '/logs/2024/08/site/css/a.css').read() == 'b{}', 'S3: F5 uploads a folder in one go')
        await k.press('Tab'); await k.press('F7'); await sp.wait_for_selector('#din'); await sp.fill('#din', 'archive'); await k.press('Enter'); await sp.wait_for_timeout(1500)
        check(os.path.exists(s3 + '/logs/2024/08/archive/.ng-dir') and '/archive' in '\n'.join(await srows()), 'S3: F7 creates a folder marker')
        await spick('app-01.log'); await k.press('F6'); await sp.wait_for_selector('#din'); await sp.fill('#din', 'first.log'); await k.press('Enter'); await sp.wait_for_timeout(1500)
        check(os.path.exists(s3 + '/logs/2024/08/first.log') and not os.path.exists(s3 + '/logs/2024/08/app-01.log'), 'S3: F6 renames an object')
        await spick('site'); await k.press('F8'); await sp.wait_for_selector('#dw.on'); t = await sp.inner_text('#dw'); await sp.wait_for_timeout(150); await k.press('Tab'); await k.press('Enter'); await sp.wait_for_timeout(1500)
        await sp.click('#dw [data-b="0"]') if await sp.locator('#dw.on').count() else None; await sp.wait_for_timeout(1500)
        check('no Trash' in t and not os.path.exists(s3 + '/logs/2024/08/site'), 'S3: F8 warns there is no Trash and deletes a folder')
        await s3link('s3://logs/big/', 2000); await k.press('End'); await sp.wait_for_timeout(200); r = await srows()
        check('obj-00999' in r[-2] and 'more' in r[-1], 'S3: a big prefix shows the first 1000 objects and a "more" row')
        await k.press('Enter'); await sp.wait_for_timeout(1500); h1 = await sp.inner_text('#hint'); await k.press('End'); await k.press('Enter'); await sp.wait_for_timeout(1500); h2 = await sp.inner_text('#hint')
        await k.press('End'); await sp.wait_for_timeout(200); r = await srows()
        check('2000 entries' in h1 and '2500 entries' in h2 and 'obj-02499' in r[-1] and not any('more' in x for x in r), 'S3: Enter on "more" loads the next pages')
        await s3link('s3://', 1500); check(any('/logs' in x for x in await srows()), 'S3: s3:// lists the buckets')
        await s3link('minio s3://logs/ http://localhost:9000'); log = open(s3log).read()
        check('--profile minio --endpoint-url http://localhost:9000' in log and 'minio@localhost_9000:s3://logs' in await sp.inner_text('#pR .ttl'), 'S3: profile and endpoint URL (MinIO style) reach the aws command')
        await s3link('nocreds s3://logs/', 1500); t = await sp.inner_text('#dw')
        check('credentials' in t, 'S3: missing credentials give a clear error'); await k.press('Enter'); await sp.wait_for_timeout(200)
        # SQLite: system sqlite3 on the live disk
        import sqlite3 as _sq
        os.makedirs(harness.FAKE_HOME + '/data'); dbp = harness.FAKE_HOME + '/data/shop.sqlite'; con = _sq.connect(dbp)
        con.executescript("CREATE TABLE customers(id INTEGER PRIMARY KEY, name TEXT, city TEXT); CREATE TABLE orders(id INTEGER PRIMARY KEY, customer INTEGER, total REAL, note TEXT); CREATE VIEW big_orders AS SELECT * FROM orders WHERE total > 100;")
        con.executemany('INSERT INTO customers VALUES (?,?,?)', [(1, 'Anna', 'Faenza'), (2, 'Bruno', 'Bologna'), (3, 'Carla, "la rossa"', 'Ravenna')])
        con.executemany('INSERT INTO orders VALUES (?,?,?,?)', [(i, 1 + i % 3, i * 1.5, 'riga\ncon a capo' if i == 7 else None) for i in range(1, 20001)]); con.commit(); con.close()
        open(harness.FAKE_HOME + '/data/Thumbs.db', 'wb').write(b'\xd0\xcf\x11\xe0 not sqlite')
        q = await b.new_page(viewport={'width': 1300, 'height': 800}); q.on('pageerror', lambda e: errs.append(str(e)))
        await harness.attach(q); await q.goto(URL); await q.wait_for_timeout(1500); k = q.keyboard
        async def qrows(pn='pL'): return await q.eval_on_selector_all(f'#{pn} .row', 'e=>e.map(x=>x.textContent)')
        async def qpick(n, pn='pL'): r = await qrows(pn); await q.click(f'#{pn} .row[data-i="{[i for i,t in enumerate(r) if n in t][0]}"]')
        async def qgo(n, w=1200): await qpick(n); await k.press('Enter'); await q.wait_for_timeout(w)
        async def sql(t, w=1500): await k.type(t); await k.press('Enter'); await q.wait_for_timeout(w)
        await k.type('cd ~/data'); await k.press('Enter'); await q.wait_for_timeout(500); await k.press('Tab'); await k.type('cd ~/out'); await k.press('Enter'); await q.wait_for_timeout(500); await k.press('Tab')
        await qgo('shop.sqlite'); t = '\n'.join(await qrows())
        check('(SQLite, read-only)' in await q.inner_text('#pL .ttl') and all(x in t for x in ['schema.sql', '/tables', '/views', '/queries']) and 'sqlite shop.sqlite>' in await q.inner_text('#prompt'), 'sqlite: Enter opens a database as a folder (sqlite3)')
        await qgo('tables', 600); await qpick('customers.csv'); await k.press('F3'); await q.wait_for_timeout(800)
        check(await q.locator('#ovb table.csvt').count() == 1 and 'Carla, "la rossa"' in await q.inner_text('#ovb'), 'sqlite: F3 shows a table as a grid'); await k.press('Escape'); await q.wait_for_timeout(200)
        await qpick('orders.csv'); await k.press('F5'); await q.wait_for_selector('#dw.on'); await q.wait_for_timeout(150); await k.press('Enter'); await q.wait_for_timeout(2500)
        exp_csv = subprocess.run(['sqlite3', '-readonly', '-csv', '-header', dbp, 'SELECT * FROM "orders"'], capture_output=True).stdout
        check(open(harness.FAKE_HOME + '/out/orders.csv', 'rb').read() == exp_csv, 'sqlite: F5 exports a 20000-row table to CSV')
        await sql("SELECT city, count(*) AS n FROM customers JOIN orders ON orders.customer = customers.id GROUP BY city ORDER BY city")
        v = await q.inner_text('#ovb'); check(q.url and 'Bologna' in v and '6667' in v and 'Faenza' in v, 'sqlite: SQL typed on the command line shows the result')
        await k.press('Escape'); await q.wait_for_timeout(200); await qgo('..', 500); await qgo('queries', 600)
        check(any('001-select-city-count' in r and '.csv' in r for r in await qrows()), 'sqlite: query results are kept in queries/')
        await sql("DELETE FROM customers"); t = await q.inner_text('#dw')
        check('read' in t.lower() and 'only' in t.lower(), 'sqlite: writing queries are refused'); await k.press('Enter'); await q.wait_for_timeout(200)
        await qgo('..', 500); await qgo('..', 600); await qgo('Thumbs.db', 800)
        check('~/data' in await q.inner_text('#pL .ttl') and not await q.locator('#dw.on').count(), 'sqlite: a .db that is not SQLite is not treated as one')
        if await q.locator('#ov.on, body.ov').count(): await k.press('Escape'); await q.wait_for_timeout(200)
        # SQLite: sql.js on the demo drive (needs http, WebAssembly does not load from file://)
        import http.server, threading, functools
        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *a): pass
        srv_h = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(Quiet, directory=str(ROOT)))
        threading.Thread(target=srv_h.serve_forever, daemon=True).start()
        dm = await b.new_page(viewport={'width': 1300, 'height': 800}); dm.on('pageerror', lambda e: errs.append(str(e)))
        await dm.goto(f'http://127.0.0.1:{srv_h.server_address[1]}/index.html'); await dm.wait_for_timeout(1500); k = dm.keyboard
        await k.type('cd /intel'); await k.press('Enter'); await dm.wait_for_timeout(500)
        r = await dm.eval_on_selector_all('#pL .row', 'e=>e.map(x=>x.textContent)'); await dm.click(f'#pL .row[data-i="{[i for i,t in enumerate(r) if "agents.sqlite" in t][0]}"]'); await k.press('Enter'); await dm.wait_for_timeout(2500)
        check('(SQLite, read-only)' in await dm.inner_text('#pL .ttl') and 'sql.js' in await dm.inner_text('#hint'), 'sqlite: demo drive opens agents.sqlite with sql.js')
        await k.type("SELECT codename FROM active_agents ORDER BY clearance DESC"); await k.press('Enter'); await dm.wait_for_timeout(1500)
        v = await dm.inner_text('#ovb'); check(v.find('HERON') < v.find('KESTREL') < v.find('OSPREY') and v.find('HERON') >= 0, 'sqlite: sql.js runs a query on a view')
        await dm.screenshot(path=str(OUT / 'sqlite.png')); srv_h.shutdown()
        print('page errors:', errs or 'none')
        check(not errs, 'no page errors')
        await b.close()
    sys.exit(1 if fails else 0)

asyncio.run(run())
