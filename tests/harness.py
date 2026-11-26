# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Francesco Fullone
"""Fake Claude desktop API for local tests.

Injects window.claude.use('desktop') backed by a real folder on this machine
(FAKE_HOME), so the LIVE DISK mode can be tested in Chromium with Playwright.
fs.*, shell.trashItem (moves into FAKE_TRASH), childProcess.exec (real shell,
used by git; tests/fakebin/ssh stands in for ssh) and a minimal pty that runs each line through the real shell are provided.
"""
import os, base64, shutil, subprocess

FAKE_HOME = os.environ.get('NG_FAKE_HOME', '/tmp/ng-fakehome')
FAKE_TRASH = os.environ.get('NG_FAKE_TRASH', '/tmp/ng-faketrash')

def _st(p):
    s = os.stat(p)
    return {'size': s.st_size, 'mtimeMs': s.st_mtime * 1000, 'isDirectory': os.path.isdir(p),
            'isFile': os.path.isfile(p), 'isSymbolicLink': False, 'mode': s.st_mode, 'ctimeMs': 0, 'birthtimeMs': 0}

async def fsop(op, args):
    try:
        if op == 'readdir':
            return {'ok': [{'name': n, 'isFile': os.path.isfile(os.path.join(args[0], n)),
                            'isDirectory': os.path.isdir(os.path.join(args[0], n)), 'isSymbolicLink': False}
                           for n in os.listdir(args[0])]}
        if op == 'stat': return {'ok': _st(args[0])}
        if op == 'exists': return {'ok': os.path.exists(args[0])}
        if op == 'readFile':
            b = open(args[0], 'rb').read()
            if len(args) > 1 and args[1] == 'utf8': return {'ok': b.decode()}
            if len(args) > 1 and args[1] == 'base64': return {'ok': base64.b64encode(b).decode()}
            return {'ok': base64.b64encode(b).decode(), 'bytes': True}
        if op == 'writeFile':
            if args[2] == 'b64': open(args[0], 'wb').write(base64.b64decode(args[1]))
            else: open(args[0], 'w', newline='').write(args[1])
            return {'ok': None}
        if op == 'mkdir': os.mkdir(args[0]); return {'ok': None}
        if op == 'rename': os.rename(args[0], args[1]); return {'ok': None}
        if op == 'copyFile': shutil.copyfile(args[0], args[1]); return {'ok': None}
        if op == 'rm': os.remove(args[0]); return {'ok': None}
        if op == 'rmdir': os.rmdir(args[0]); return {'ok': None}
        if op == 'trash':
            os.makedirs(FAKE_TRASH, exist_ok=True)
            shutil.move(args[0], os.path.join(FAKE_TRASH, os.path.basename(args[0]))); return {'ok': None}
    except FileNotFoundError as e: return {'err': 'ENOENT: ' + str(e)}
    except FileExistsError as e: return {'err': 'EEXIST: ' + str(e)}
    except OSError as e: return {'err': 'EIO: ' + str(e)}

FAKEBIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fakebin')

async def sh(cmd, opts):
    env = {**os.environ, 'PATH': FAKEBIN + os.pathsep + os.environ.get('PATH', '')}
    r = subprocess.run(cmd, shell=True, capture_output=True, timeout=60, env=env)
    return {'stdout': r.stdout.decode('utf-8', 'replace'), 'stderr': r.stderr.decode('utf-8', 'replace'),
            'code': r.returncode, 'signal': None, 'truncated': False}

STUB = r'''
(()=>{const call=async(op,...a)=>{const r=await window.__fs(op,a);if(r.err)throw new Error(r.err);if(r.bytes){const s=atob(r.ok),u=new Uint8Array(s.length);for(let i=0;i<s.length;i++)u[i]=s.charCodeAt(i);return u}return r.ok};
const b64=u=>{let s='';for(const c of u)s+=String.fromCharCode(c);return btoa(s)};
const D={install:{state:async()=>'installed'},permissions:{state:async()=>'granted'},app:{dock:{setIcon:async x=>{window.__icon=x;return {written:true}}}},
fs:{readdir:p=>call('readdir',p),stat:p=>call('stat',p),exists:p=>call('exists',p),readFile:(p,e)=>call('readFile',p,e),
writeFile:(p,d,e)=>typeof d==='string'?call('writeFile',p,d,'utf8'):call('writeFile',p,b64(d),'b64'),mkdir:p=>call('mkdir',p),rename:(a,b)=>call('rename',a,b),copyFile:(a,b)=>call('copyFile',a,b),rm:p=>call('rm',p),rmdir:p=>call('rmdir',p)},
os:{homedir:async()=>'__HOME__',username:async()=>'tester',hostname:async()=>'testbox',platform:async()=>'linux',tmpdir:async()=>'/tmp'},
shell:{trashItem:p=>call('trash',p),openPath:async p=>console.log('OPEN',p),showItemInFolder:async p=>console.log('REVEAL',p)},
childProcess:{exec:(c,o)=>window.__sh(c,o||{})},
pty:{spawn:(f,a,o)=>{let cb=()=>{},buf='';window.__ptyLog=[];return {pid:Promise.resolve(1),onData:c=>{cb=c;setTimeout(()=>c('$ '),10)},onExit(){},onError(){},write:async d=>{window.__ptyLog.push(d);for(const ch of d){if(ch==='\r'){cb('\r\n');const line=buf;buf='';if(line.trim()){const r=await window.__sh(line,{});cb((r.stdout+r.stderr).replace(/\n/g,'\r\n'))}cb('$ ')}else if(ch==='\x7f'){if(buf){buf=buf.slice(0,-1);cb('\b \b')}}else{buf+=ch;cb(ch)}}},resize:async()=>{},kill:async()=>{}}}}};
window.claude={use:async n=>n==='desktop'?D:null};})();
'''.replace('__HOME__', FAKE_HOME)

async def attach(page):
    """Call before page.goto() to run the page in LIVE DISK mode on FAKE_HOME."""
    await page.expose_function('__fs', fsop)
    await page.expose_function('__sh', sh)
    await page.add_init_script(STUB)
