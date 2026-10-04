# Benchmarks (synthetic data only)

> **Read this first.** Every number below was measured on **synthetic, generated scans** (clean typography,
> mild noise, mild rotation). Real documents (stamps, handwriting, photographs of paper, skewed or
> low-contrast scans, tables, multi-column layouts) are harder, so **real-world recall is unknown and
> expected to be lower**. Treat these results as a regression baseline and a way to compare settings,
> not as an accuracy guarantee. Human review of every output remains mandatory.

## What is measured

The benchmark (`benchmarks/`) generates scanned A4 PDFs (raster-only pages, no text layer) with ground truth:

* 3 valid CPFs per page (formatted `000.000.000-00` or 11 raw digits), in assorted fonts/sizes
  (Arial, Times, Courier, Verdana, Georgia, Calibri on the machine that ran it);
* decoys that must **not** be redacted: a CPF with a wrong check digit, a valid CNPJ, a date/time, a process
  number and a phone number;
* body text filling the page, Gaussian blur, Gaussian noise (sigma 8 = "clean scan", sigma 28 = "poor scan"),
  speckles and a random rotation of +-1.2 degrees. Pages are 300 DPI JPEG (q80) embedded in an A4 PDF.

Two things are evaluated per `(render DPI, Tesseract psm)` configuration:

1. **Detection** (`OCREngine.get_grounding_map` + `find_cpfs_in_grounding` on the original PDF rendered at the
   given DPI): CPF-level recall/precision (value match), and *box coverage* (share of ground-truth CPF boxes whose
   centre falls inside a redaction box produced by `Session.get_redaction_boxes`; conservative, because the centre
   of a CPF split across several OCR words can fall in the gap between word boxes).
2. **Verification** (`utils.verifier.verify_pdf` on a *final* PDF built like the pipeline does: 1240 px wide,
   JPEG q75). Two final PDFs are built from the same pages: **leaky** (only the first CPF of each page is
   blacked out, so 2 CPFs/page leak) and **clean** (all three blacked out). Reported: share of leaked CPFs the
   verifier finds, and clean pages wrongly flagged.

Times are wall-clock seconds per page (render + OCR), measured with 4 parallel worker processes, each Tesseract
single-threaded, on a 20-core Windows 10 machine with Tesseract 5.4.1 (`por` traineddata). Treat them as
relative, not absolute.

## Reproduce

```bash
python -m benchmarks.run_benchmark --pages 10 --dpis 200 300 400 --psms 3 6 11 --workers 4 --seed 42 --noise 8 \
    --out benchmarks/results/synthetic_noise8.json
```

Requires Tesseract (set `TESSERACT_PATH`/`TESSDATA_PREFIX` if it is not on the PATH). The corpus is deterministic
for a given `--seed`; the full JSON (per-page rows included) of the runs reported here is in `benchmarks/results/`.

## Results, 10 pages, 30 valid CPFs, 20 leaked CPFs (seed 42)

### Clean scan (noise sigma 8) - `synthetic_noise8.json`

| render DPI | psm | CPF recall | precision | box coverage | s/page (detection) |
|---:|---:|---:|---:|---:|---:|
| 200 | 3 / 6 / 11 | 100 % | 100 % | 100 % | 4.3 - 4.7 |
| 300 | 3 / 6 / 11 | 100 % | 100 % | 100 % | 7.2 - 7.6 |
| 400 | 3 / 6 / 11 | 96.7 % (29/30) | 100 % | 96.7 % | 10.9 - 11.2 |

Verification (final PDF, 1240 px, JPEG q75): **20/20 leaked CPFs found and 0/10 clean pages flagged for every
combination of verify DPI 200/300/400 and psm 3/6/11.** Time 3.7 s/page at 200 DPI, 5.1 - 5.7 s/page at 300 - 400 DPI.

### Poor scan (noise sigma 28) - `synthetic_noise28.json`

| render DPI | psm | CPF recall | precision | box coverage | s/page (detection) |
|---:|---:|---:|---:|---:|---:|
| 200 | 3 / 6 | 96.7 % | 100 % | 96.7 % | 4.3 - 4.4 |
| 200 | 11 | 96.7 % | 96.7 % (1 false CPF) | 96.7 % | 4.3 |
| 300 | 3 / 6 / 11 | 100 % | 100 % | 100 % | 7.6 - 7.7 |
| 400 | 3 / 6 / 11 | 93.3 % (28/30) | 100 % | 93.3 % | 10.2 - 11.5 |

Verification again found **20/20 leaks with 0/10 clean pages flagged** in all nine configurations (4.2 - 7.1 s/page).

### Higher resolution probe - `synthetic_dpi600_probe.json` (4 pages, 12 CPFs, psm 3, sigma 8)

| render DPI | CPF recall | precision | box coverage | s/page (detection) | verify at 600 DPI: leak recall |
|---:|---:|---:|---:|---:|---:|
| 600 | 75 % (9/12) | 90 % (1 false CPF) | 50 % | 21.4 | 87.5 % (7/8) |

## What the numbers say (and do not say)

* On this synthetic corpus **300 DPI was the best detection setting**; 200 DPI was nearly as good and ~40 % faster.
  Recall **dropped at 400 and especially 600 DPI**: Tesseract fragments digits into small tokens at large render
  sizes, which makes digit sequences harder to join into one CPF. The project default `BASE_DPI=1000` was **not
  measured** (a single A4 page takes minutes); on this evidence it is outside the range where the synthetic scans
  behave best. This may differ for real scans, so measure on your own (permitted) data before changing the default.
* `psm` 3, 6 and 11 gave the same recall on clean synthetic text; differences would only appear on messier layouts.
  The only false CPFs observed were one with psm 11 at 200 DPI (poor scan) and one with psm 3 at 600 DPI.
* The post-redaction verifier was perfect here (no missed leaks, no false alarms) even at 200 DPI on a 1240 px
  JPEG; that is expected for clean typography and says little about handwriting, stamps or poor photographs.
  The dpi=600 probe shows it is not immune to OCR fragmentation either (7/8).
* Not measured: handwriting, signatures with CPFs written nearby, YOLO accuracy, vision-LLM address discovery,
  address matching quality (see `tests/test_address_matching.py` for the characterisation of over/under-redaction),
  PDFs with a native text layer (those are verified by exact text extraction, not OCR).
* Sample sizes are small (30 CPFs): one miss moves recall by 3.3 points. Use the JSON files for per-page detail.
