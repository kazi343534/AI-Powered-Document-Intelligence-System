# Bundled Tesseract language data

`eng.traineddata` is the English (LSTM) model from the official
[`tessdata_fast`](https://github.com/tesseract-ocr/tessdata_fast) repository.

- Source: https://github.com/tesseract-ocr/tessdata_fast/blob/main/eng.traineddata
- License: Apache License 2.0 (same as Tesseract)
- Size: ~4 MB

It is bundled so the `tesserocr` OCR engine works on Render without system
packages or a runtime download. `app/ocr.py` points `PyTessBaseAPI` at this
directory unless `TESSDATA_PREFIX` / `TESSDATA_PREFIX` is configured.
