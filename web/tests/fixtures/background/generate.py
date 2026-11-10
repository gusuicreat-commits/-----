"""生成极小的三帧纯色夹具，可从项目根用后端 Python 环境运行。"""
from pathlib import Path

import pymupdf

folder = Path(__file__).resolve().parent
for index, color in enumerate(((255, 0, 0), (0, 255, 0), (0, 0, 255)), 1):
    image = pymupdf.Pixmap(pymupdf.csRGB, (0, 0, 16, 9), False)
    image.set_rect(image.irect, color)
    (folder / f'frame_{index:05d}.jpg').write_bytes(image.tobytes('jpg', jpg_quality=92))
