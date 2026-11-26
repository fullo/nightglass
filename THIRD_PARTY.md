# Librerie incluse in `vendor/`

| File | Progetto | Versione | Licenza |
|---|---|---|---|
| xterm.js, addon-fit.js | xterm.js | 5.5.0 / 0.10.0 | MIT |
| pdf.min.js, pdf.worker.min.js | PDF.js (Mozilla) | 3.11.174 | Apache-2.0 |
| mammoth.browser.min.js | mammoth.js | 1.8.0 | BSD-2-Clause |
| jszip.min.js | JSZip | 3.10.1 | MIT o GPL-3.0 (a scelta) |
| UTIF.js | UTIF.js (Photopea) | 3.1.0 | MIT |
| highlight.min.js | highlight.js | 11.9.0 | BSD-3-Clause |

I font (IBM Plex Mono, JetBrains Mono, Source Code Pro, Share Tech Mono) arrivano da Google Fonts, licenza SIL Open Font License; non sono inclusi nel repository.

PDF.js è chiamato con `isEvalSupported: false`: tienilo così (CVE-2024-4367 riguarda le versioni precedenti alla 4.2.67 con eval attivo).

## Compatibilità con la licenza del progetto

Il progetto è `GPL-2.0-or-later`. MIT, BSD-2-Clause e BSD-3-Clause sono compatibili con la GPL-2.0. Apache-2.0 (pdf.js) è compatibile con la GPL-3.0 ma non con la sola GPL-2.0: la distribuzione che include pdf.js vale quindi sotto GPL-3.0 o successive. Se togli pdf.js, tutto resta compatibile anche con la sola GPL-2.0.
