# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Francesco Fullone
"""Smoke test: demo drive + live disk (fake desktop API) + git + archives.

Needs: Python 3, `pip install playwright`, `playwright install chromium`, git, tar.
Run from the repository root:  python3 tests/smoke.py
Screenshots go to tests/out/.
"""
import asyncio, os, pathlib, shutil, subprocess, sys
from playwright.async_api import async_playwright
sys.path.insert(0, os.path.dirname(__file__))
import harness

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
        print('page errors:', errs or 'none')
        check(not errs, 'no page errors')
        await b.close()
    sys.exit(1 if fails else 0)

asyncio.run(run())
