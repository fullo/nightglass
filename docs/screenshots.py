# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Francesco Fullone
"""Regenerate the README screenshots in docs/screenshots/.

Run from the repository root:  python3 docs/screenshots.py
Needs the same setup as tests/smoke.py (Playwright + Chromium, git, tar).
Demo-drive shots use the built-in sample files; live-disk shots use the
fake desktop API from tests/harness.py on a throwaway folder.
"""
import asyncio, os, pathlib, shutil, subprocess, sys, tarfile, io
from playwright.async_api import async_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tests'))
import harness, mailfixtures

URL = (ROOT / 'index.html').as_uri()
OUT = ROOT / 'docs' / 'screenshots'
W, H = 1280, 760


def fake_home():
    h = harness.FAKE_HOME
    shutil.rmtree(h, ignore_errors=True); shutil.rmtree(harness.FAKE_TRASH, ignore_errors=True)
    os.makedirs(h + '/Documents'); os.makedirs(h + '/radar')
    g = lambda *a: subprocess.run(['git', *a], cwd=h + '/radar', check=True, capture_output=True)
    g('init', '-q', '-b', 'main'); g('config', 'user.email', 'dev@example.org'); g('config', 'user.name', 'Dev')
    os.makedirs(h + '/radar/src')
    open(h + '/radar/src/scan.py', 'w').write('def scan(host):\n    return [22, 80]\n')
    open(h + '/radar/README.md', 'w').write('# Radar\n')
    open(h + '/radar/requirements.txt', 'w').write('requests\n')
    g('add', '.'); g('commit', '-qm', 'first version')
    g('checkout', '-qb', 'feature/ipv6')
    open(h + '/radar/src/scan.py', 'w').write('def scan(host, v6=False):\n    return [22, 80, 443]\n')
    open(h + '/radar/src/ipv6.py', 'w').write('PREFIX = "fd00::"\n'); g('add', '.'); g('commit', '-qm', 'IPv6 support')
    g('checkout', '-q', 'main')
    open(h + '/radar/README.md', 'a').write('Scanner for the lab network.\n')
    open(h + '/radar/notes.txt', 'w').write('todo\n')
    for n in ('report-2026-01.pdf', 'report-2026-02.pdf', 'photo 1.jpg', 'photo 2.jpg'):
        open(h + '/Documents/' + n, 'wb').write(b'x' * 1024)
    b = io.BytesIO()
    with tarfile.open(fileobj=b, mode='w:gz') as t:
        for name, data in [('backup/config.yml', b'port: 8080\n'), ('backup/db/dump.sql', b'CREATE TABLE t (id int);\n'), ('backup/README.txt', b'nightly backup\n')]:
            ti = tarfile.TarInfo(name); ti.size = len(data); t.addfile(ti, io.BytesIO(data))
    open(h + '/backup-2026-11-25.tgz', 'wb').write(b.getvalue())
    mailfixtures.main(h + '/Mail'); os.remove(h + '/Mail/expected.json')
    # a fake S3 store for tests/fakebin/aws, and a small SQLite database
    s3 = os.environ.setdefault('NG_FAKE_S3', '/tmp/ng-fakes3'); shutil.rmtree(s3, ignore_errors=True)
    import random, sqlite3; rnd = random.Random(7)
    for m in ('09', '10', '11'): os.makedirs(f'{s3}/logs/2026/{m}')
    for d in range(1, 27): open(f'{s3}/logs/2026/11/api-2026-11-{d:02d}.log.gz', 'wb').write(os.urandom(rnd.randint(20000, 90000)))
    os.makedirs(f'{s3}/backups/db'); open(f'{s3}/backups/db/shop-2026-11-25.sqlite.gz', 'wb').write(os.urandom(50000))
    os.makedirs(h + '/data'); con = sqlite3.connect(h + '/data/shop.sqlite')
    con.executescript('CREATE TABLE customers(id INTEGER PRIMARY KEY, name TEXT, city TEXT, since TEXT);'
                      'CREATE TABLE orders(id INTEGER PRIMARY KEY, customer INTEGER REFERENCES customers(id), day TEXT, total_eur REAL, status TEXT);'
                      'CREATE VIEW open_orders AS SELECT * FROM orders WHERE status <> "delivered";')
    cs = [('Anna Ricci', 'Faenza'), ('Bruno Galli', 'Bologna'), ('Carla Conti', 'Ravenna'), ('Davide Moro', 'Forlì'), ('Elena Sala', 'Imola'), ('Fabio Riva', 'Cesena')]
    con.executemany('INSERT INTO customers VALUES (?,?,?,?)', [(i + 1, n, c, f'202{rnd.randint(1, 5)}-0{rnd.randint(1, 9)}-1{rnd.randint(0, 9)}') for i, (n, c) in enumerate(cs)])
    con.executemany('INSERT INTO orders VALUES (?,?,?,?,?)', [(i, rnd.randint(1, 6), f'2026-11-{1 + i % 26:02d}', round(rnd.uniform(12, 480), 2), rnd.choice(['delivered', 'delivered', 'shipped', 'paid'])) for i in range(1, 241)])
    con.commit(); con.close()


async def row(pg, panel, name):
    rows = await pg.eval_on_selector_all(f'#{panel} .row', 'e=>e.map(x=>x.textContent)')
    i = [k for k, r in enumerate(rows) if name in r][0]
    await pg.click(f'#{panel} .row[data-i="{i}"]')


async def main():
    OUT.mkdir(parents=True, exist_ok=True); fake_home()
    shot = lambda pg, n: pg.screenshot(path=str(OUT / f'{n}.png'))
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={'width': W, 'height': H}); k = pg.keyboard
        await pg.goto(URL); await pg.wait_for_timeout(1500)

        async def cmd(c, w=500):
            await k.type(c); await k.press('Enter'); await pg.wait_for_timeout(w)

        await k.press('Insert'); await k.press('ArrowDown'); await k.press('Insert'); await pg.wait_for_timeout(200)
        await shot(pg, '01-panels')
        # 00-skins.gif: the same screen in every skin
        await pg.click('#mb [data-m="3"]'); await pg.click('#dd [data-mi="0"]'); await pg.wait_for_timeout(200)
        names = await pg.eval_on_selector_all('#dd [data-mi]', 'e=>e.map(x=>x.textContent.trim())'); await k.press('Escape'); frames = []
        for i in range(len(names)):
            await pg.click('#mb [data-m="3"]'); await pg.click('#dd [data-mi="0"]'); await pg.click(f'#dd [data-mi="{i}"]'); await pg.wait_for_timeout(250)
            await pg.evaluate("document.querySelector('#hint') && (document.querySelector('#hint').style.visibility='hidden')")
            frames.append(await pg.screenshot()); await pg.evaluate("document.querySelector('#hint') && (document.querySelector('#hint').style.visibility='')")
        from PIL import Image
        imgs = [Image.open(io.BytesIO(f)).convert('RGB').quantize(colors=128, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE) for f in frames]
        imgs[0].save(OUT / '00-skins.gif', save_all=True, append_images=imgs[1:], duration=1400, loop=0, optimize=True)
        await pg.click('#mb [data-m="3"]'); await pg.click('#dd [data-mi="0"]'); await pg.click('#dd [data-mi="0"]'); await pg.wait_for_timeout(200)
        await cmd('cd /tools'); await row(pg, 'pL', 'scanner.js'); await k.press('F3'); await pg.wait_for_timeout(1200)
        await shot(pg, '03-viewer-code'); await k.press('Escape')
        await k.press('F4'); await pg.wait_for_timeout(800); await shot(pg, '05-editor'); await k.press('F10'); await pg.wait_for_timeout(300)
        await cmd('cd /intel'); await row(pg, 'pL', 'dossier.pdf'); await k.press('F3'); await pg.wait_for_timeout(1800)
        await shot(pg, '04-preview-pdf'); await k.press('Escape')
        await cmd('cd /ops/nightglass'); await row(pg, 'pL', 'floorplan'); await k.press('F3'); await pg.wait_for_timeout(300)
        await k.press('F4'); await k.press('F2'); await k.type('5841'); await pg.wait_for_timeout(200)
        await shot(pg, '06-hex-editor'); await k.press('F10'); await pg.wait_for_timeout(200)
        await pg.wait_for_selector('#dw.on', timeout=3000); await pg.click('#dw [data-b="1"]'); await pg.wait_for_timeout(300);
        await row(pg, 'pL', 'safehouse.odt'); await k.press('Control+x'); await k.press('q'); await pg.wait_for_timeout(1800)
        await shot(pg, '07-quick-view'); await k.press('Control+x'); await k.press('q'); await pg.wait_for_timeout(200)
        await k.press('Control+x'); await k.press('r'); await pg.wait_for_timeout(300)
        await pg.fill('#bf', r'^(\w+?)_'); await pg.dispatch_event('#bf', 'input')
        await pg.fill('#br', '{n:2}-$1-'); await pg.dispatch_event('#br', 'input'); await pg.wait_for_timeout(200)
        await shot(pg, '08-batch-rename'); await k.press('Escape')
        await cmd('ls -l /intel', 400); await cmd('grep -rn pier /', 400); await cmd('tree /ops', 600)
        await shot(pg, '02-console'); await k.press('Control+o'); await pg.wait_for_timeout(200)
        await cmd('cd /comms'); await row(pg, 'pL', 'exfil_0419.tgz'); await k.press('Enter'); await pg.wait_for_timeout(800)
        await row(pg, 'pL', 'exfil'); await k.press('Enter'); await pg.wait_for_timeout(400)
        await shot(pg, '09-archive'); await cmd('cd /')
        for sk in ['Dracula', 'Eclipse', 'Neon (Synthwave)']:
            await pg.click('#mb [data-m="3"]'); await pg.click('#dd [data-mi="0"]'); await pg.click(f'#dd button:has-text("{sk}")'); await pg.wait_for_timeout(200)
            await cmd('cd /tools'); await row(pg, 'pL', 'scanner.js')
            await k.press('Control+x'); await k.press('q'); await pg.wait_for_timeout(1000)
            await shot(pg, '12-skin-' + sk.split()[0].lower())
            await k.press('Control+x'); await k.press('q'); await pg.wait_for_timeout(200)
        await pg.click('#mb [data-m="3"]'); await pg.click('#dd [data-mi="0"]'); await pg.click('#dd button:has-text("Midnight Commander")')
        await k.press('F1'); await pg.wait_for_timeout(200); await pg.click('#mantoc [data-h="batch"]'); await pg.wait_for_timeout(200)
        await shot(pg, '13-manual'); await k.press('Escape')

        lv = await b.new_page(viewport={'width': W, 'height': H}); k = lv.keyboard
        await harness.attach(lv); await lv.goto(URL); await lv.wait_for_timeout(1500)
        async def lcmd(c, w=700):
            await k.type(c); await k.press('Enter'); await lv.wait_for_timeout(w)
        await lcmd('cd ~/radar'); await k.press('Tab'); await lcmd('cd ~/radar'); await k.press('Tab')
        await k.press('Control+x'); await k.press('g'); await lv.wait_for_timeout(700)
        await shot(lv, '10-git-branches')
        items = await lv.eval_on_selector_all('#dd [data-mi]', 'e=>e.map(x=>x.textContent)')
        await lv.click(f'#dd [data-mi="{[i for i, t in enumerate(items) if "ipv6" in t][0]}"]'); await lv.wait_for_timeout(300); await k.press('Enter'); await lv.wait_for_timeout(900)
        await lcmd('cd ~/radar/src'); await lv.wait_for_timeout(300)
        await shot(lv, '11-git-browse')
        await lcmd('git log --oneline', 1200)
        await shot(lv, '14-terminal'); await k.press('Control+o')
        srv = os.environ.get('NG_FAKE_SERVER', '/tmp/ng-fakeserver'); shutil.rmtree(srv, ignore_errors=True)
        os.makedirs(srv + '/www/site/assets'); open(srv + '/www/site/index.html', 'w').write('<h1>Lab</h1>\n'); open(srv + '/www/site/style.css', 'w').write('body{margin:0}\n'); open(srv + '/www/site/assets/logo.svg', 'w').write('<svg/>')
        await lv.wait_for_timeout(300); await k.press('Control+x'); await k.press('g'); await lv.wait_for_timeout(500); await lv.click('#dd [data-mi="0"]'); await lv.wait_for_timeout(800)
        await lcmd('cd ~/Documents')
        await k.press('Tab'); await k.press('Control+x'); await k.press('s'); await lv.wait_for_selector('#din'); await lv.fill('#din', 'deploy@lab-server' + srv + '/www/site'); await k.press('Enter'); await lv.wait_for_timeout(1500)
        await k.press('Tab'); await k.press('Insert'); await k.press('Insert'); await lv.wait_for_timeout(200)
        await shot(lv, '16-ssh')
        await k.press('Tab'); await lv.click('#pR .row[data-i="0"]'); await k.press('Enter'); await lv.wait_for_timeout(800)
        await k.press('Tab'); await lcmd('cd ~/Mail'); await row(lv, 'pL', 'inbox.mbox'); await k.press('Enter'); await lv.wait_for_timeout(900)
        await row(lv, 'pL', '0001'); await k.press('Enter'); await lv.wait_for_timeout(700)
        await k.press('Tab'); await lcmd('cd ~/Documents'); await k.press('Tab'); await row(lv, 'pL', 'Fattura'); await k.press('Insert'); await row(lv, 'pL', 'logo.png'); await k.press('Insert'); await lv.wait_for_timeout(200)
        await shot(lv, '17-mail-folder')
        await lcmd('cd ~/Mail'); await row(lv, 'pL', 'sample.eml'); await k.press('F3'); await lv.wait_for_timeout(1500)
        await shot(lv, '18-mail-preview'); await k.press('Escape'); await lv.wait_for_timeout(300)
        await lcmd('cd ~/data'); await row(lv, 'pL', 'shop.sqlite'); await k.press('Enter'); await lv.wait_for_timeout(1200)
        await k.type("SELECT c.city, count(*) AS orders, round(sum(o.total_eur), 2) AS total_eur FROM orders o JOIN customers c ON c.id = o.customer GROUP BY c.city ORDER BY total_eur DESC"); await k.press('Enter'); await lv.wait_for_timeout(1500)
        await shot(lv, '20-sqlite-query'); await k.press('Escape'); await lv.wait_for_timeout(300)
        await row(lv, 'pL', 'tables'); await k.press('Enter'); await lv.wait_for_timeout(500); await row(lv, 'pL', 'orders.csv')
        await k.press('Control+x'); await k.press('q'); await lv.wait_for_timeout(1500)
        await shot(lv, '21-sqlite-table'); await k.press('Control+x'); await k.press('q'); await lv.wait_for_timeout(300)
        await lcmd('cd ~/Documents'); await k.press('Tab')
        await k.press('Control+x'); await k.press('3'); await lv.wait_for_selector('#din'); await lv.fill('#din', 's3://logs/2026/11/'); await k.press('Enter'); await lv.wait_for_timeout(1800)
        await k.press('Insert'); await k.press('Insert'); await k.press('Insert'); await lv.wait_for_timeout(200)
        await shot(lv, '19-s3')

        ph = await b.new_page(viewport={'width': 390, 'height': 780}, has_touch=True, is_mobile=True)
        await ph.goto(URL); await ph.wait_for_timeout(1200); await shot(ph, '15-phone')
        await b.close()
    print('screenshots in', OUT)

asyncio.run(main())
