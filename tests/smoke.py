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
        print('page errors:', errs or 'none')
        check(not errs, 'no page errors')
        await b.close()
    sys.exit(1 if fails else 0)

asyncio.run(run())
