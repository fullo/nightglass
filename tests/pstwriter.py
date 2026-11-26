# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 Francesco Fullone
"""A small writer of Outlook .pst files, after [MS-PST], for the tests.

Writes Unicode or ANSI files, with no, "compressible" (permute) or "high"
(cyclic) encoding: header with CRCs, AMap pages, node and block BTrees, data
trees (XBLOCK), subnode trees (SLBLOCK, SIBLOCK), heap on node, BTH, property
and table contexts, message store, folders with hierarchy and contents tables,
messages with recipient and attachment tables, attachments and embedded
messages. With small=True the BTrees, heaps and subnode trees are split into
many small pieces, so a tiny file exercises every multi-level case.

The output is checked with libpff (pip install libpff-python) when available.
"""
import struct, zlib

import base64, os, re
def _table():
    """mpbbCrypt of [MS-PST] section 5.1 (R, S and I = inverse of R), from index.html, to keep one copy"""
    html = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'index.html'), encoding='utf-8').read()
    m = re.search(r"const PSTX=Uint8Array\.from\(atob\('([A-Za-z0-9+/=]+)'\)", html)
    t = base64.b64decode(m.group(1)); assert len(t) == 768
    R, S, I = t[:256], t[256:512], t[512:]
    assert sorted(R) == list(range(256)) and all(I[R[k]] == k for k in range(256))
    return R, S, I
R, S, I = _table()

def crc(d): return zlib.crc32(d, 0xFFFFFFFF) ^ 0xFFFFFFFF
def sig(ib, bid): x = (ib ^ bid) & 0xFFFFFFFF; return ((x >> 16) ^ x) & 0xFFFF
def cyclic(b, key):
    w = (key ^ (key >> 16)) & 0xFFFF; o = bytearray(len(b))
    for i, c in enumerate(b):
        c = (c + w) & 255; c = R[c]; c = (c + (w >> 8)) & 255; c = S[c]; c = (c - (w >> 8)) & 255; c = I[c]; o[i] = (c - w) & 255; w = (w + 1) & 0xFFFF
    return bytes(o)

def filetime(ms): return int(ms * 10**4 + 116444736000000000)

PT_I16, PT_I32, PT_BOOL, PT_I64, PT_TIME, PT_STR8, PT_UNI, PT_BIN, PT_OBJ = 0x2, 0x3, 0xB, 0x14, 0x40, 0x1E, 0x1F, 0x102, 0xD
NID_FOLDER, NID_MSG, NID_ATT, NID_HIER, NID_CONT, NID_ASSOC, NID_LTP = 0x02, 0x04, 0x05, 0x0D, 0x0E, 0x0F, 0x1F

class Pst:
    def __init__(self, ansi=False, crypt=1, small=False, codepage=1252):
        self.W = not ansi; self.BS = 8 if self.W else 4; self.crypt = crypt; self.small = small; self.cp = codepage
        self.MAXB = 8176 if self.W else 8180
        self.blocks = {}          # bid -> plain payload
        self.nbt = {}             # nid -> (bidData, bidSub, nidParent)
        self.nb = 1; self.ltp = 0x100; self.np = 1; self.nidx = {}

    # ---------- NDB ----------
    def bid(self, internal=False): b = self.nb * 4 | (2 if internal else 0); self.nb += 1; return b
    def put(self, payload, internal=False):
        assert len(payload) <= self.MAXB, len(payload)
        b = self.bid(internal); self.blocks[b] = bytes(payload); return b
    def tree(self, chunks):
        """data tree over explicit chunks (each one data block)"""
        if not chunks: return 0
        bids = [self.put(c) for c in chunks]
        if len(bids) == 1: return bids[0]
        full = (self.MAXB - 8) // self.BS; per = 4 if self.small else full
        total = sum(len(c) for c in chunks); f = '<Q' if self.W else '<I'
        x = lambda lvl, ids, sz: self.put(struct.pack('<BBHI', 1, lvl, len(ids), sz) + b''.join(struct.pack(f, i) for i in ids), True)
        if len(bids) <= per: return x(1, bids, total)
        xs = [x(1, bids[i:i + per], sum(len(c) for c in chunks[i:i + per])) for i in range(0, len(bids), per)]
        assert len(xs) <= full
        return x(2, xs, total)
    def data(self, payload):
        n = self.MAXB if not self.small else 1000
        return self.tree([payload[i:i + n] for i in range(0, len(payload), n)] or [b''])
    def subtree(self, ents):
        """subnode BTree over (nid, bidData, bidSub)"""
        if not ents: return 0
        ents = sorted(ents); f = '<Q' if self.W else '<I'; pad = b'\0\0\0\0' if self.W else b''
        per = (self.MAXB - len(pad) - 4) // (3 * self.BS)
        if self.small: per = 2
        sls = []
        for i in range(0, len(ents), per):
            part = ents[i:i + per]
            sls.append((part[0][0], self.put(struct.pack('<BBH', 2, 0, len(part)) + pad + b''.join(struct.pack('<' + f[1] * 3, *e) for e in part), True)))
        if len(sls) == 1: return sls[0][1]
        return self.put(struct.pack('<BBH', 2, 1, len(sls)) + pad + b''.join(struct.pack('<' + f[1] * 2, n, b) for n, b in sls), True)
    def nid(self, t, idx=None):
        if idx is None: self.ltp += 1; idx = self.ltp
        return (idx << 5) | t

    # ---------- LTP ----------
    def heap(self, sig_):
        return Heap(self, sig_)
    def node(self, nid, obj, parent=0):
        """obj: (chunks, subnode entries) from a heap -> NBT node"""
        chunks, subs = obj; self.nbt[nid] = (self.tree(chunks), self.subtree(subs), parent); return nid
    def subnode(self, nid, obj):
        chunks, subs = obj; return (nid, self.tree(chunks), self.subtree(subs))

    def value(self, h, typ, v):
        """value for a PC record or a TC cell: returns 4 bytes (or 8 inline in TC)"""
        if typ in (PT_I16, PT_I32, PT_BOOL): return struct.pack('<i', int(v))
        if typ == PT_UNI: v = v.encode('utf-16le')
        elif typ == PT_STR8: v = v.encode('cp%d' % self.cp)
        return struct.pack('<I', h.var(v))

    def pc(self, props, subs=()):
        """props: list of (id, type, value); subs: extra subnode entries. Returns (chunks, subs)"""
        h = self.heap(0xBC); recs = []
        for pid, typ, v in sorted(props, key=lambda x: x[0]):
            if typ in (PT_TIME, PT_I64): raw = struct.pack('<I', h.alloc(struct.pack('<Q', filetime(v) if typ == PT_TIME else v)))
            elif typ == PT_OBJ: raw = struct.pack('<I', h.alloc(struct.pack('<II', v[0], v[1])))
            else: raw = self.value(h, typ, v)
            recs.append(struct.pack('<HH', pid, typ) + raw)
        h.root = h.bth(recs, 2, 6)
        h.subs += list(subs)
        return h.build()

    def tc(self, cols, rows, subs=()):
        """cols: list of (id, type); rows: list of (rowid, {id: value}). Returns (chunks, subs)"""
        h = self.heap(0x7C)
        cols = [(0x67F2, PT_I32), (0x67F3, PT_I32)] + [c for c in cols if c[0] not in (0x67F2, 0x67F3)]
        size = lambda t: 8 if t in (PT_TIME, PT_I64) else 2 if t == PT_I16 else 1 if t == PT_BOOL else 4
        desc = {}; ib = 0
        for grp in (4, 2, 1):
            for c in cols:
                s = size(c[1])
                if (s >= 4) == (grp == 4) and (grp == 4 or s == grp): desc[c] = [ib, s]; ib += s
            if grp == 4: e4 = ib
            elif grp == 2: e2 = ib
            else: e1 = ib
        for k, c in enumerate(cols): desc[c].append(k)
        rs = e1 + (len(cols) + 7) // 8
        matrix = []
        for i, (rid, vals) in enumerate(rows):
            r = bytearray(rs); vals = {**vals, 0x67F2: rid, 0x67F3: 0}
            for c in cols:
                if c[0] not in vals or vals[c[0]] is None: continue
                o, s, bit = desc[c]; t, v = c[1], vals[c[0]]
                if t == PT_TIME: b = struct.pack('<Q', filetime(v))
                elif t == PT_I64: b = struct.pack('<q', v)
                elif t == PT_I16: b = struct.pack('<h', v)
                elif t == PT_BOOL: b = bytes([1 if v else 0])
                else: b = self.value(h, t, v)
                r[o:o + s] = b; r[e1 + bit // 8] |= 0x80 >> (bit % 8)
            matrix.append(bytes(r))
        ri = h.bth(sorted(struct.pack('<I', rid) + struct.pack('<I' if self.W else '<H', i) for i, (rid, _) in enumerate(rows)), 4, 4 if self.W else 2)
        allr = b''.join(matrix)
        if not rows: hn = 0
        elif len(allr) <= 3580 and not (self.small and len(rows) > 3):
            hn = h.alloc(allr)
        else:
            per = self.MAXB // rs
            if self.small: per = 3
            chunks = [b''.join(matrix[i:i + per]) for i in range(0, len(matrix), per)]
            n = self.nid(NID_LTP); h.subs.append((n, self.tree(chunks), 0)); hn = n
        info = struct.pack('<BBHHHHIII', 0x7C, len(cols), e4, e2, e1, rs, ri, hn, 0)
        info += b''.join(struct.pack('<IHBB', (c[0] << 16) | c[1], *desc[c]) for c in sorted(cols, key=lambda c: (c[0] << 16) | c[1]))
        h.root = h.alloc(info)
        h.subs += list(subs)
        return h.build()

    # ---------- write ----------
    def write(self, path):
        W, BS = self.W, self.BS; f = '<Q' if W else '<I'
        AM, AMSPAN = 0x4400, 253952      # an AMap page every 253,952 bytes from 0x4400
        out = bytearray(AM); amaps = set(); cur = [AM]
        def place(size, align):
            while True:
                p = (cur[0] + align - 1) // align * align
                a = AM + -(-(p - AM) // AMSPAN) * AMSPAN      # next AMap at or after p
                if p == a or p + size > a:
                    amaps.add(a); cur[0] = a + 512; continue
                cur[0] = p + size; return p
        trl = 16 if W else 12
        bbt = []
        for b, payload in sorted(self.blocks.items()):
            enc = payload
            if not b & 2 and self.crypt == 1: enc = bytes(R[x] for x in payload)
            elif not b & 2 and self.crypt == 2: enc = cyclic(payload, b & 0xFFFFFFFF)
            tot = (len(enc) + trl + 63) // 64 * 64; ib = place(tot, 64)
            blk = enc + b'\0' * (tot - trl - len(enc))
            blk += struct.pack('<HHIQ', len(enc), sig(ib, b), crc(enc), b) if W else struct.pack('<HHII', len(enc), sig(ib, b), b, crc(enc))
            self._at(out, ib, blk); bbt.append((b, ib, len(enc)))
        # BTrees
        def pages(entries, cb, ptype):
            """entries: list of (key, bytes) sorted; returns (bid, ib) of the root"""
            lvl = 0; area = 488 if W else 496
            while True:
                per = area // cb
                if self.small: per = min(per, 4)
                nodes = []
                for i in range(0, len(entries), per):
                    part = entries[i:i + per]; pb = self.np * 4; self.np += 1; ib = place(512, 512)
                    pg = b''.join(e[1] for e in part).ljust(area, b'\0') + struct.pack('<BBBB', len(part), area // cb, cb, lvl)
                    pg = pg.ljust(496 if W else 500, b'\0')
                    c = crc(pg)
                    pg += struct.pack('<BBHIQ', ptype, ptype, sig(ib, pb), c, pb) if W else struct.pack('<BBHII', ptype, ptype, sig(ib, pb), pb, c)
                    self._at(out, ib, pg); nodes.append((part[0][0], pb, ib))
                if len(nodes) == 1: return nodes[0][1], nodes[0][2]
                entries = [(k, struct.pack('<' + f[1] * 3, k, pb, ib)) for k, pb, ib in nodes]; cb = 3 * BS; lvl += 1
        nbt = [(n, struct.pack(f, n) + struct.pack('<' + f[1] * 2, d, s) + struct.pack('<I', p) + (b'\0' * 4 if W else b''))
               for n, (d, s, p) in sorted(self.nbt.items())]
        bbte = [(b, struct.pack('<' + f[1] * 2, b, ib) + struct.pack('<HH', cb, 2) + (b'\0' * 4 if W else b'')) for b, ib, cb in bbt]
        nroot = pages(nbt, 32 if W else 16, 0x81); broot = pages(bbte, 24 if W else 12, 0x80)
        eof = (cur[0] + 511) // 512 * 512
        if len(out) < eof: out += b'\0' * (eof - len(out))
        # AMap pages: everything up to EOF is allocated
        free = 0
        for a in sorted(amaps | {AM}):
            if a >= eof: continue
            bits = bytearray(496)
            for k in range(min(AMSPAN, eof - a) // 64): bits[k // 8] |= 0x80 >> (k % 8)
            bits = bytes(bits).ljust(496 if W else 500, b'\0'); pb = 0; c = crc(bits)
            self._at(out, a, bytes(bits) + (struct.pack('<BBHIQ', 0x84, 0x84, 0, c, pb) if W else struct.pack('<BBHII', 0x84, 0x84, 0, pb, c)))
        last = max(a for a in amaps | {AM} if a < eof)
        # header
        h = bytearray(564 if W else 512)
        struct.pack_into('<4s', h, 0, b'!BDN'); struct.pack_into('<2sHHBB', h, 8, b'SM', 23 if W else 14, 19, 1, 1)
        rgnid = [0x400] * 32
        for n in self.nbt: t = n & 31; rgnid[t] = max(rgnid[t], (n >> 5) + 1)
        if W:
            struct.pack_into('<QQI', h, 24, 0, self.np * 4, 0x1234)
            struct.pack_into('<32I', h, 44, *rgnid)
            struct.pack_into('<IQQQQQQQQBBH', h, 180, 0, eof, last, free, 0, nroot[0], nroot[1], broot[0], broot[1], 2, 0, 0)
            h[256:384] = b'\xff' * 128; h[384:512] = b'\xff' * 128
            h[512] = 0x80; h[513] = self.crypt; struct.pack_into('<Q', h, 516, self.nb * 4)
            struct.pack_into('<I', h, 4, crc(bytes(h[8:8 + 471]))); struct.pack_into('<I', h, 524, crc(bytes(h[8:524])))
        else:
            struct.pack_into('<III', h, 24, self.nb * 4, self.np * 4, 0x1234)
            struct.pack_into('<32I', h, 36, *rgnid)
            struct.pack_into('<IIIIIIIIIBBH', h, 164, 0, eof, last, free, 0, nroot[0], nroot[1], broot[0], broot[1], 2, 0, 0)
            h[204:332] = b'\xff' * 128; h[332:460] = b'\xff' * 128
            h[460] = 0x80; h[461] = self.crypt
            struct.pack_into('<I', h, 4, crc(bytes(h[8:8 + 471])))
        out[0:len(h)] = h
        open(path, 'wb').write(bytes(out))
        return len(out)
    @staticmethod
    def _at(out, ib, b):
        if len(out) < ib + len(b): out += b'\0' * (ib + len(b) - len(out))
        out[ib:ib + len(b)] = b

class Heap:
    """heap on node: items in blocks, each block one data block"""
    def __init__(self, pst, sig_):
        self.p = pst; self.sig = sig_; self.items = [[]]; self.root = 0; self.subs = []
        self.cap = pst.MAXB if not pst.small else 300
    def _hdr(self, k): return 12 if k == 0 else 66 if k % 128 == 8 else 2
    def _size(self, k, extra=0, n=0):
        it = self.items[k]; body = self._hdr(k) + sum(len(x) for x in it) + extra
        return body + (body & 1) + 4 + 2 * (len(it) + n + 1)
    def alloc(self, data):
        assert len(data) <= 3580
        k = len(self.items) - 1
        if self.items[k] and self._size(k, len(data), 1) > min(self.cap, self.p.MAXB):
            self.items.append([]); k += 1
        self.items[k].append(bytes(data)); return (k << 16) | (len(self.items[k]) << 5)
    def var(self, b):
        if not b: return 0
        if len(b) <= 3580 and not (self.p.small and len(b) > 600): return self.alloc(b)
        n = self.p.nid(NID_LTP); self.subs.append((n, self.p.data(b), 0)); return n
    def bth(self, recs, ck, ce):
        hdr = self.alloc(b'\0' * 8)
        per = 3580 // (ck + ce)
        if self.p.small: per = 3
        lvl = 0; level = list(recs)
        if not level: root = 0
        else:
            while True:
                grp = [level[i:i + per] for i in range(0, len(level), per)]
                hids = [(g[0][:ck], self.alloc(b''.join(g))) for g in grp]
                if len(hids) == 1: root = hids[0][1]; break
                level = [k + struct.pack('<I', hid) for k, hid in hids]; lvl += 1
                per = 3580 // (ck + 4) if not self.p.small else 3
        k, i = hdr >> 16, ((hdr >> 5) & 0x7FF) - 1
        self.items[k][i] = struct.pack('<BBBBI', 0xB5, ck, ce, lvl, root)
        return hdr
    def build(self):
        chunks = []
        for k, it in enumerate(self.items):
            h = self._hdr(k); body = bytearray(h)
            offs = []
            for x in it: offs.append(len(body)); body += x
            offs.append(len(body))
            if len(body) & 1: body += b'\0'
            pm = len(body)
            body += struct.pack('<HH', len(it), 0) + b''.join(struct.pack('<H', o) for o in offs)
            struct.pack_into('<H', body, 0, pm)
            if k == 0: struct.pack_into('<BBI', body, 2, 0xEC, self.sig, self.root)
            chunks.append(bytes(body))
        return chunks, self.subs

# ---------- messaging layer ----------
def entryid(nid): return b'\0' * 4 + bytes(range(16)) + struct.pack('<I', nid)

def message_obj(p, m, depth=0):
    """m: dict(subject, sender:(name, addr), to:[(name, addr)], cc:[...], date(ms), body, html(bytes), rtf(bytes),
    headers, atts:[dict(name, data, mime, cid) | dict(name, msg)]) -> (chunks, subs)"""
    props = [(0x001A, PT_UNI, 'IPM.Note'), (0x0037, PT_UNI, '\x01\x01' + m['subject'] if m.get('prefix') else m['subject']),
             (0x0E07, PT_I32, 1), (0x3FDE, PT_I32, m.get('cpid', 65001 if p.W else p.cp))]
    if not p.W: props = [(i, PT_STR8 if t == PT_UNI else t, v) for i, t, v in props]
    S = PT_UNI if p.W else PT_STR8
    if m.get('sender'): props += [(0x0C1A, S, m['sender'][0]), (0x0C1F, S, m['sender'][1]), (0x5D01, S, m['sender'][1])]
    if m.get('date'): props += [(0x0039, PT_TIME, m['date']), (0x0E06, PT_TIME, m['date'])]
    if m.get('body'): props.append((0x1000, S, m['body']))
    if m.get('html'): props.append((0x1013, PT_BIN, m['html']))
    if m.get('rtf'): props.append((0x1009, PT_BIN, m['rtf']))
    if m.get('headers'): props.append((0x007D, S, m['headers']))
    for _ in range(m.get('pad', 0)): props.append((0x8000 + _, S, 'proprietà di riempimento %d ' % _ * 4))
    rec = [(k, {0x0C15: t, 0x3001: n, 0x3003: a, 0x39FE: a, 0x3000: k}) for k, (t, (n, a)) in enumerate([(1, x) for x in m.get('to', [])] + [(2, x) for x in m.get('cc', [])])]
    props.append((0x0E04, S, '; '.join(n for n, a in m.get('to', []))))
    subs = [p.subnode(0x692, p.tc([(0x0C15, PT_I32), (0x3001, S), (0x3003, S), (0x39FE, S), (0x3000, PT_I32)], rec))]
    arows = []
    for k, a in enumerate(m.get('atts', [])):
        anid = p.nid(NID_ATT, 0x400 + k + depth * 0x40)
        ap = [(0x3705, PT_I32, 5 if 'msg' in a else 1), (0x370B, PT_I32, -1), (0x3707, S, a['name']), (0x3704, S, a['name'][:8]), (0x3001, S, a['name'])]
        asubs = []
        if 'msg' in a:
            enid = p.nid(NID_MSG, 0x500 + k + depth * 0x40); eo = message_obj(p, a['msg'], depth + 1)
            asubs.append(p.subnode(enid, eo)); ap.append((0x3701, PT_OBJ, (enid, 0)))
            ap.append((0x0E20, PT_I32, 1000))
        else:
            ap += [(0x3701, PT_BIN, a['data']), (0x370E, S, a.get('mime', 'application/octet-stream')), (0x0E20, PT_I32, len(a['data']) + 200)]
            if a.get('cid'): ap.append((0x3712, S, a['cid']))
        subs.append(p.subnode(anid, p.pc(ap, asubs)))
        arows.append((anid, {0x3704: a['name'][:8], 0x3705: 5 if 'msg' in a else 1, 0x0E20: 100, 0x370B: -1}))
    subs.append(p.subnode(0x671, p.tc([(0x3704, S), (0x3705, PT_I32), (0x0E20, PT_I32), (0x370B, PT_I32)], arows)))
    return p.pc(props, subs)

def build(path, folders, ansi=False, crypt=1, small=False, name='Cartella personale'):
    """folders: list of dict(name, msgs:[message dict], kids:[folders]). Returns file size."""
    p = Pst(ansi=ansi, crypt=crypt, small=small); S = PT_UNI if p.W else PT_STR8
    TOP, SEARCH = p.nid(NID_FOLDER, 0x401), p.nid(NID_FOLDER, 0x402)
    p.node(0x21, p.pc([(0x0FF9, PT_BIN, bytes(range(16))), (0x3001, S, name), (0x35E0, PT_BIN, entryid(TOP)), (0x35E7, PT_BIN, entryid(SEARCH))]))
    # name-to-id map with one entry: numeric named property 0x8501 of the first GUID in the GUID stream (wGuid 3)
    p.node(0x61, p.pc([(0x0001, PT_I32, 251), (0x0002, PT_BIN, bytes.fromhex('0820060000000000c000000000000046')),
                       (0x0003, PT_BIN, struct.pack('<IHH', 0x8501, 3 << 1, 0)), (0x0004, PT_BIN, b'\0' * 4)]))
    hcols = [(0x3001, S), (0x3602, PT_I32), (0x3603, PT_I32), (0x360A, PT_BOOL)]
    ccols = [(0x0037, S), (0x0E06, PT_TIME), (0x0039, PT_TIME), (0x0C1A, S), (0x0E07, PT_I32), (0x0E08, PT_I32)]
    counter = [0x403]
    def folder(nid, fname, parent, msgs, kids):
        kn = []
        for k in kids:
            knid = p.nid(NID_FOLDER, counter[0]); counter[0] += 1; kn.append((knid, k)); folder(knid, k['name'], nid, k.get('msgs', []), k.get('kids', []))
        p.node(nid, p.pc([(0x3001, S, fname), (0x3602, PT_I32, len(msgs)), (0x3603, PT_I32, 0), (0x360A, PT_BOOL, 1 if kids else 0)]), parent)
        p.node(nid - (nid & 31) + NID_HIER, p.tc(hcols, [(knid, {0x3001: k['name'], 0x3602: len(k.get('msgs', [])), 0x3603: 0, 0x360A: 1 if k.get('kids') else 0}) for knid, k in kn]))
        rows = []
        for m in msgs:
            mnid = p.nid(NID_MSG, counter[0]); counter[0] += 1
            p.node(mnid, message_obj(p, m), nid)
            rows.append((mnid, {0x0037: m['subject'], 0x0E06: m.get('date'), 0x0039: m.get('date'), 0x0C1A: (m.get('sender') or ('', ''))[0] or None, 0x0E07: 1, 0x0E08: 1000}))
        p.node(nid - (nid & 31) + NID_CONT, p.tc(ccols, rows))
        p.node(nid - (nid & 31) + NID_ASSOC, p.tc([(0x001A, S)], []))
    folder(0x122, '', 0, [], [])
    # the root folder lists the IPM subtree and the search root
    p.node(0x12D, p.tc(hcols, [(TOP, {0x3001: 'Top of Personal Folders', 0x3602: 0, 0x360A: 1}), (SEARCH, {0x3001: 'Search Root', 0x3602: 0, 0x360A: 0})]))
    p.node(0x122, p.pc([(0x3001, S, ''), (0x3602, PT_I32, 0), (0x360A, PT_BOOL, 1)]), 0x122)
    folder(TOP, 'Top of Personal Folders', 0x122, [], folders)
    folder(SEARCH, 'Search Root', 0x122, [], [])
    return p.write(path)
