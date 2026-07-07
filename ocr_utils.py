# -*- coding: utf-8 -*-
"""共享 OCR 工具：优先 PaddleOCR 3.x（中文准），装不上自动退到 Tesseract。

PaddleOCR 3.x + paddlepaddle 3.x 有一个 oneDNN/PIR 执行器兼容 bug，
必须在 import paddle 之前用环境变量禁掉 PIR-in-executor 和 mkldnn，否则报
"ConvertPirAttribute2RuntimeAttribute not support"。
"""

import os

# 必须在 import paddle/paddleocr 之前设置
os.environ["FLAGS_enable_pir_in_executor"] = "0"
os.environ["FLAGS_enable_pir_api"] = "0"
os.environ["FLAGS_use_mkldnn"] = "0"

import numpy as np

_OCR = None
_BACKEND = None


def _try_paddleocr():
    global _OCR, _BACKEND
    try:
        from paddleocr import PaddleOCR
        # 3.x 参数：禁 mkldnn，禁文本行方向分类（弹窗文字基本水平，不需要）
        _OCR = PaddleOCR(lang="ch", enable_mkldnn=False, use_textline_orientation=False)
        _BACKEND = "paddleocr"
        return True
    except Exception as e:
        print(f"[OCR] PaddleOCR 不可用: {e}")
        return False


def _try_tesseract():
    global _OCR, _BACKEND
    try:
        import pytesseract
        _OCR = pytesseract
        _BACKEND = "tesseract"
        return True
    except Exception as e:
        print(f"[OCR] Tesseract 不可用: {e}")
        return False


def init_ocr():
    """初始化 OCR 引擎，返回后端名。两个都装不上则抛异常。"""
    if _OCR is not None:
        return _BACKEND
    if _try_paddleocr():
        print(f"[OCR] 使用 PaddleOCR（推荐，中文准确）")
        return _BACKEND
    if _try_tesseract():
        print(f"[OCR] 使用 Tesseract（中文准确度较低，建议装 PaddleOCR）")
        return _BACKEND
    raise SystemExit(
        "[OCR] 两个后端都不可用。\n"
        "  推荐: pip install paddleocr paddlepaddle\n"
        "  备用: pip install pytesseract 并安装 Tesseract-OCR 程序(需中文语言包 chi_sim)"
    )


def _to_ndarray(img):
    """接受 PIL.Image 或路径或 ndarray，统一转成 ndarray。"""
    if isinstance(img, np.ndarray):
        return img
    if isinstance(img, str):
        from PIL import Image
        return np.array(Image.open(img).convert("RGB"))
    # 假定是 PIL.Image
    return np.array(img.convert("RGB"))


def ocr_image(img) -> str:
    """对 PIL.Image / 图片路径 / ndarray 做 OCR，返回拼接后的纯文本。"""
    init_ocr()
    if _BACKEND == "paddleocr":
        arr = _to_ndarray(img)
        try:
            res = _OCR.predict(arr)
        except Exception as e:
            # 个别版本 predict 不接受 ndarray，退回路径
            raise RuntimeError(f"paddleocr predict 失败: {e}")
        texts = []
        if res:
            item = res[0]
            # 3.x: OCRResult 对象，rec_texts 是 list[str]
            rec = None
            try:
                rec = item["rec_texts"]
            except Exception:
                try:
                    rec = item.rec_texts
                except Exception:
                    rec = None
            if rec:
                texts = list(rec)
        return "\n".join(texts)
    else:  # tesseract
        from PIL import Image
        if isinstance(img, str):
            img = Image.open(img)
        elif isinstance(img, np.ndarray):
            img = Image.fromarray(img)
        return _OCR.image_to_string(img, lang="chi_sim+eng")
