# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Francesco Fullone
"""Sample mail files for the tests: an .eml, an .mbox and an Outlook .msg.

  python3 tests/mailfixtures.py DIR     writes sample.eml, inbox.mbox, sample.msg
                                        and expected.json (attachment bytes, as SHA-256)

The .msg is written by a small OLE compound file writer below, so the tests
need no Outlook. If `extract_msg` is installed (pip install extract_msg),
the .msg is read back with it as an independent check.
"""
import email.policy, hashlib, json, os, struct, sys
from email.message import EmailMessage

PNG = bytes.fromhex('89504e470d0a1a0a0000000d4948445200000001000000010806000000'
                    '1f15c4890000000d49444154789c6360f80f0000010101005d4f7c2e0000000049454e44ae426082')
PDF = b'%PDF-1.4\n% fake pdf for tests\n' + bytes(range(256)) * 40 + b'\n%%EOF\n'   # > 4096: regular sectors in .msg

def sha(b): return hashlib.sha256(b).hexdigest()

def make_eml():
    inner = EmailMessage(policy=email.policy.SMTP)
    inner['From'] = 'Anna Bianchi <anna@example.org>'; inner['To'] = 'team@example.org'
    inner['Subject'] = 'Verbale della riunione'; inner['Date'] = 'Tue, 17 Nov 2026 09:00:00 +0100'
    inner.set_content('Il verbale è in allegato.\n')
    m = EmailMessage(policy=email.policy.SMTP)
    m['From'] = 'Mario Rossi <mario@example.com>'; m['To'] = 'Francesco <f@example.it>'; m['Cc'] = 'Lucia <lucia@example.com>'
    m['Subject'] = 'Riunione di lunedì: ordine del giorno ✓'; m['Date'] = 'Fri, 20 Nov 2026 18:30:00 +0100'
    m['Message-ID'] = '<abc123@example.com>'
    m.set_content('Ciao,\nlunedì alle 10 parliamo del budget.\nFrom the desk of Mario\n\n— Mario\n')
    m.add_alternative('<p>Ciao,<br>luned&igrave; alle <b>10</b> parliamo del budget.</p>'
                      '<p><img src="cid:logo@example.com" alt="logo"> <img src="https://tracker.example.com/open.gif?u=1"></p>', subtype='html')
    m.get_payload()[1].add_related(PNG, maintype='image', subtype='png', cid='<logo@example.com>', filename='logo.png', disposition='inline')
    m.add_attachment(PDF, maintype='application', subtype='pdf', filename='Fattura €42.pdf')
    m.add_attachment(inner)
    return m.as_bytes()

def make_mbox(eml):
    m2 = EmailMessage(policy=email.policy.SMTP)
    m2['From'] = 'Négoce <ventes@example.fr>'; m2['To'] = 'f@example.it'
    m2['Subject'] = 'Offre spéciale'; m2['Date'] = 'Mon, 02 Nov 2026 08:15:00 +0000'
    m2.set_content('Prix réduits.\nFrom now on, everything is cheaper.\n', charset='iso-8859-1', cte='base64')
    m3 = b'From: nobody@example.com\nSubject: no date here\n\nplain old message\n>From the archive\n'
    out = b''
    for i, raw in enumerate([eml, m2.as_bytes(), m3]):
        raw = raw.replace(b'\r\n', b'\n')
        raw = b'\n'.join((b'>' + l) if l.lstrip(b'>').startswith(b'From ') else l for l in raw.split(b'\n'))   # mboxrd
        out += b'From sender@example.com Sat Nov 21 10:0%d:00 2026\n' % i + raw.rstrip(b'\n') + b'\n\n'
    return out

# ---------- minimal OLE compound file (CFB v3) writer ----------
FREE, END, FATS = 0xFFFFFFFF, 0xFFFFFFFE, 0xFFFFFFFD

def cfb(tree):
    """tree: dict name -> bytes (stream) or dict (storage). Returns file bytes."""
    ents = [{'name': 'Root Entry', 'type': 5, 'kids': [], 'data': None}]
    def add(d, parent):
        for n, v in d.items():
            e = {'name': n, 'type': 1 if isinstance(v, dict) else 2, 'kids': [], 'data': None if isinstance(v, dict) else v}
            ents.append(e); ents[parent]['kids'].append(len(ents) - 1)
            if isinstance(v, dict): add(v, len(ents) - 1)
    add(tree, 0)
    mini = b''; big = []
    for e in ents[1:]:
        if e['type'] != 2: continue
        if len(e['data']) < 4096:
            e['mst'] = len(mini) // 64 if e['data'] else END; mini += e['data'] + b'\0' * (-len(e['data']) % 64)
        else: big.append(e)
    nmini = len(mini) // 64
    def secs(n): return (n + 511) // 512
    ndir, nmf, nms = secs(len(ents) * 128), secs(nmini * 4), secs(len(mini))
    nbig = sum(secs(len(e['data'])) for e in big)
    nfat = 1
    while nfat * 128 < nfat + ndir + nmf + nms + nbig: nfat += 1
    assert nfat <= 109
    fat = [FREE] * (nfat * 128); pos = 0; body = []
    def chain(n, data):
        nonlocal pos
        if n == 0: return END
        st = pos
        for i in range(n): fat[pos + i] = pos + i + 1 if i < n - 1 else END
        pos += n; body.append(data + b'\0' * (n * 512 - len(data))); return st
    for i in range(nfat): fat[i] = FATS
    pos = nfat
    # directory (filled later, reserve)
    dir_st = pos; pos += ndir
    for i in range(ndir): fat[dir_st + i] = dir_st + i + 1 if i < ndir - 1 else END
    mf_data = b''.join(struct.pack('<I', i + 1 if i < nmini - 1 else END) for i in range(nmini))
    mf_st = chain(nmf, mf_data)
    ms_st = chain(nms, mini)
    for e in big: e['st'] = chain(secs(len(e['data'])), e['data'])
    # red-black tree: siblings as a right-leaning chain sorted by CFB order, all black
    key = lambda i: (len(ents[i]['name']), ents[i]['name'].upper())
    left = [FREE] * len(ents); right = [FREE] * len(ents); child = [FREE] * len(ents)
    for i, e in enumerate(ents):
        ks = sorted(e['kids'], key=key)
        if ks: child[i] = ks[0]
        for a, b in zip(ks, ks[1:]): right[a] = b
    d = b''
    for i, e in enumerate(ents):
        nm = e['name'].encode('utf-16le') + b'\0\0'
        if e['type'] == 5: st, size = (ms_st if nmini else END), len(mini)
        elif e['type'] == 1: st, size = 0, 0
        else: size = len(e['data']); st = e['st'] if size >= 4096 else e['mst']
        d += nm.ljust(64, b'\0') + struct.pack('<HBBIII', len(nm), e['type'], 1, left[i], right[i], child[i]) + b'\0' * 36 + struct.pack('<IQ', st, size)
    d += b'\0' * (ndir * 512 - len(d))
    hdr = bytes.fromhex('d0cf11e0a1b11ae1') + b'\0' * 16 + struct.pack('<HHHHH', 0x3E, 3, 0xFFFE, 9, 6) + b'\0' * 6
    hdr += struct.pack('<IIIIIIIII', 0, nfat, dir_st, 0, 4096, mf_st if nmini else END, nmf, END, 0)
    hdr += b''.join(struct.pack('<I', i if i < nfat else FREE) for i in range(109))
    fatb = b''.join(struct.pack('<I', x) for x in fat)
    out = hdr + fatb + d + b''.join(body)
    return out

def u16(s): return s.encode('utf-16le')   # stream data has no NUL; the size in the property list counts it
def ft(y, mo, d, h, mi):  # FILETIME of a UTC time
    import calendar
    return (calendar.timegm((y, mo, d, h, mi, 0)) + 11644473600) * 10**7

def props(hsz, fixed, strs, header=b''):
    b = header.ljust(hsz, b'\0')
    for tag, val in fixed:
        t = tag & 0xFFFF
        if t == 0x40: b += struct.pack('<IIQ', tag, 6, val)
        else: b += struct.pack('<IIiI', tag, 6, val, 0)
    for tag, size in strs: b += struct.pack('<IIII', tag, 6, size, 0)
    return b

def msg_storage(subject, body, hsz, extra=None, fixed=(), sender=None):
    s = {'__substg1.0_001A001F': u16('IPM.Note')}
    strs = []
    def put(pid, typ, data):
        name = '__substg1.0_%04X%04X' % (pid, typ); s[name] = data; strs.append(((pid << 16) | typ, len(data) + (2 if typ == 0x1F else 1 if typ == 0x1E else 0)))
    put(0x0037, 0x001F, u16(subject)) if subject is not None else None
    put(0x1000, 0x001F, u16(body))
    if sender: put(0x0C1A, 0x001F, u16(sender[0])); put(0x5D01, 0x001F, u16(sender[1]))
    for k, v in (extra or {}).items(): put(k[0], k[1], v)
    s['__properties_version1.0'] = props(hsz, fixed, strs)
    return s

def make_msg():
    import compressed_rtf
    rtf = compressed_rtf.compress(b'{\\rtf1\\ansi Ciao dal formato RTF, ripetuto: RTF RTF RTF RTF RTF.}', compressed=True)
    html = '<html><head><meta charset="utf-8"></head><body><p>Il <b>report</b> è pronto.</p><img src="cid:img1@x"></body></html>'.encode('utf-8')
    top = msg_storage('Report trimestrale Q3 — versione finale', 'Ciao,\nil report è pronto.\n\nSaluti', 32,
        sender=('Giulia Verdi', 'giulia@example.com'),
        extra={(0x0E04, 0x001F): u16('Francesco Fullone'), (0x1013, 0x0102): html, (0x1009, 0x0102): rtf,
               (0x007D, 0x001F): u16('Received: from mx.example.com\r\nX-Mailer: Outlook\r\n')},
        fixed=[(0x0E060040, ft(2026, 11, 19, 14, 5)), (0x00390040, ft(2026, 11, 19, 14, 4)), (0x3FDE0003, 65001)])
    hdr = struct.pack('<8xIIII8x', 2, 3, 2, 3)
    top['__properties_version1.0'] = hdr + top['__properties_version1.0'][32:]
    top['__nameid_version1.0'] = {'__substg1.0_00020102': b'', '__substg1.0_00030102': b'', '__substg1.0_00040102': b''}
    def recip(name, addr, typ):
        st = {'__substg1.0_3001001F': u16(name), '__substg1.0_39FE001F': u16(addr), '__substg1.0_3003001F': u16(addr)}
        st['__properties_version1.0'] = props(8, [(0x0C150003, typ)], [(0x3001001F, len(u16(name)))])
        return st
    top['__recip_version1.0_#00000000'] = recip('Francesco Fullone', 'f@example.it', 1)
    top['__recip_version1.0_#00000001'] = recip('Paolo Neri', 'paolo@example.com', 2)
    def att(fname, data, mime, cid=None):
        st = {'__substg1.0_3707001F': u16(fname), '__substg1.0_3704001F': u16(fname[:8]), '__substg1.0_37010102': data, '__substg1.0_370E001F': u16(mime)}
        if cid: st['__substg1.0_3712001F'] = u16(cid)
        st['__properties_version1.0'] = props(8, [(0x37050003, 1)], [(0x37010102, len(data))])
        return st
    top['__attach_version1.0_#00000000'] = att('report Q3 €.pdf', PDF, 'application/pdf')
    top['__attach_version1.0_#00000001'] = att('logo.png', PNG, 'image/png', 'img1@x')
    emb = msg_storage(None, 'Testo del messaggio inoltrato.', 24, extra={(0x0037, 0x001E): 'Café alle 11'.encode('cp1252')})
    a3 = {'__substg1.0_3707001F': u16('Café alle 11'), '__substg1.0_3701000D': emb}
    a3['__properties_version1.0'] = props(8, [(0x37050003, 5)], [])
    top['__attach_version1.0_#00000002'] = a3
    return cfb(top)

def main(d):
    os.makedirs(d, exist_ok=True)
    eml = make_eml(); open(os.path.join(d, 'sample.eml'), 'wb').write(eml)
    open(os.path.join(d, 'inbox.mbox'), 'wb').write(make_mbox(eml))
    msg = make_msg(); open(os.path.join(d, 'sample.msg'), 'wb').write(msg)
    exp = {'pdf': sha(PDF), 'png': sha(PNG), 'pdf_size': len(PDF)}
    json.dump(exp, open(os.path.join(d, 'expected.json'), 'w'))
    try:
        import extract_msg
    except ImportError:
        return exp
    m = extract_msg.openMsg(os.path.join(d, 'sample.msg'))
    assert m.subject.rstrip('\0') == 'Report trimestrale Q3 — versione finale', m.subject
    assert 'il report è pronto' in m.body
    names = [getattr(a, 'longFilename', None) or getattr(a, 'name', None) for a in m.attachments]
    assert 'report Q3 €.pdf' in names, names
    pdf = [a for a in m.attachments if getattr(a, 'longFilename', '') == 'report Q3 €.pdf'][0]
    assert sha(pdf.data) == sha(PDF)
    m.close()
    print('extract_msg reads sample.msg: ok')
    return exp

if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'tests/out/mail')
