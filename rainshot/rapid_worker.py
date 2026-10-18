"""Run the optional, locally installed PP-OCRv4 models in an isolated interpreter."""
import contextlib
import json
import sys

if __name__ == '__main__':
    try:
        with contextlib.redirect_stdout(sys.stderr):
            from rapidocr_onnxruntime import RapidOCR
            engine = RapidOCR(intra_op_num_threads=2, inter_op_num_threads=2)
            result, _ = engine(sys.argv[1])
        print(json.dumps({'lines': result or []}, ensure_ascii=False))
    except Exception:
        print(json.dumps({'error': 'RapidOCR 無法執行。請在設定中檢查 Python 路徑，或重新安裝指定的引擎套件。'}, ensure_ascii=False))
        sys.exit(1)
