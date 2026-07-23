# Eval corpus

Public-domain U.S. federal government documents (17 U.S.C. sec. 105 — works of
the U.S. government are not subject to copyright). The large PDFs are fetched,
not committed, to keep the repo lean. Run before the eval:

    ./evals/download_corpus.sh

| File | Source URL |
|------|-----------|
| NIST.CSWP.29.pdf   | https://nvlpubs.nist.gov/nistpubs/CSWP/NIST.CSWP.29.pdf |
| NIST.IR.8286r1.pdf | https://nvlpubs.nist.gov/nistpubs/ir/2025/NIST.IR.8286r1.pdf |
| NIST.SP.1299.pdf   | https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.1299.pdf |
| NIST.SP.1300.pdf   | https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.1300.pdf |
| NIST.SP.1301.pdf   | https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.1301.pdf |

`ocr_test_document.pdf` is a synthetic fixture (a bar chart whose Q3 value 42
exists only in the image). It is small and committed to the repo.

Retrieved 2026-07-15.
