# Third-party code in `vendor/`

| File | Project | Version | License |
|---|---|---|---|
| `xterm.js`, `addon-fit.js` | xterm.js (`@xterm/xterm`, `@xterm/addon-fit`) | 5.5.0 / 0.10.0 | MIT |
| `pdf.min.js`, `pdf.worker.min.js` | PDF.js (`pdfjs-dist`, Mozilla) | 3.11.174 | Apache-2.0 |
| `mammoth.browser.min.js` | mammoth.js | 1.8.0 | BSD-2-Clause |
| `jszip.min.js` | JSZip | 3.10.1 | MIT or GPL-3.0 (your choice) |
| `UTIF.js` | UTIF.js (Photopea) | 3.1.0 | MIT |
| `highlight.min.js` | highlight.js (`@highlightjs/cdn-assets`) | 11.9.0 | BSD-3-Clause |

Each file is the npm release of that version, unchanged except that the trailing `//# sourceMappingURL=…` comment was removed (the source maps are not shipped).

The fonts (IBM Plex Mono, JetBrains Mono, Source Code Pro, Share Tech Mono) load from Google Fonts under the SIL Open Font License; they are not in this repository.

PDF.js is called with `isEvalSupported: false`. Keep it that way: CVE-2024-4367 affects versions before 4.2.67 when eval is allowed.

## Checksums (SHA-256)

```
e3e76115f49571e39624c3316a76b3c4c5b2c5ca518dfec4b66a9f7af8c6d059  vendor/UTIF.js
3e9ae6f6965ee1269d5574b905cf1bf559c2f44c784255b0034a71387e7719c9  vendor/addon-fit.js
837a6fa5b0c736b52bbde2b2b6190f305da3fc9ed41681db5321507057b5c846  vendor/highlight.min.js
acc7e41455a80765b5fd9c7ee1b8078a6d160bbbca455aeae854de65c947d59e  vendor/jszip.min.js
deb07bf230d1cb3e190bc5adc6743f35c6531b6571d1e5469b24f452a7f0f4ab  vendor/mammoth.browser.min.js
5b5799e6f8c680663207ac5b42ee14eed2a406fa7af48f50c154f0c0b1566946  vendor/pdf.min.js
feabdf309770ed24bba31a5467836cdc8cf639c705af27d52b585b041bb8527b  vendor/pdf.worker.min.js
7a88e46a58847d3f17109e3d48cc8aa056a01997d00ceb76035f63370712d858  vendor/xterm.js
```

Check them with `sha256sum vendor/*` (Linux) or `shasum -a 256 vendor/*` (macOS).

## Compatibility with the project license

The project is `GPL-2.0-or-later`. MIT, BSD-2-Clause and BSD-3-Clause are compatible with GPL-2.0. Apache-2.0 (PDF.js) is compatible with GPL-3.0 but not with GPL-2.0 alone, so a distribution that includes PDF.js is covered by GPL-3.0 or later. Without PDF.js, everything is also compatible with GPL-2.0 only.
