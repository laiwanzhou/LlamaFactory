# Copyright 2025 HuggingFace Inc. and the LlamaFactory team.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from pathlib import Path

import pytest
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen.canvas import Canvas


@pytest.fixture
def synthetic_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "table-a1.pdf"
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    canvas = Canvas(str(path), pagesize=landscape(A4))
    width, height = landscape(A4)
    for physical_page in range(1, 52):
        canvas.setFont("STSong-Light", 8)
        canvas.drawString(36, height - 28, "JR/T 0197—2020")
        if 17 <= physical_page <= 51:
            _draw_table_page(canvas, physical_page, width, height)
        canvas.drawRightString(width - 36, 24, str(physical_page))
        canvas.showPage()
    canvas.save()
    return path


def _draw_table_page(canvas: Canvas, physical_page: int, width: float, height: float) -> None:
    x0, top = 65.0, height - 60.0
    widths = [38, 38, 65, 42, 85, 76, 298, 49, 36]
    headers = [
        "一级子类",
        "二级子类",
        "定义说明",
        "三级子类",
        "定义说明",
        "四级子类",
        "内容",
        "最低安全级别参考",
        "备注",
    ]
    rows: list[list[str]] = []
    if physical_page == 17:
        rows = [
            ["客户", "个人", "个人对象", "个人自然信息", "自然属性", "个人基本概况信息", "姓名、证件等。", "3", ""]
        ]
    elif physical_page == 18:
        rows = [["", "", "", "个人关系信息", "关联关系", "个人间关系信息", "父母、配偶等", "3", ""]]
        rows.append(["", "", "", "", "", "跨页描述信息", "描述从本页开始", "2", ""])
    elif physical_page == 19:
        rows = [["", "", "", "", "", "", "并在下一页继续。", "", ""]]

    row_heights = [34.0] + [40.0 for _ in rows]
    xs = [x0]
    for item in widths:
        xs.append(xs[-1] + item)
    y = top
    for row_index, row_height in enumerate(row_heights):
        canvas.line(xs[0], y, xs[-1], y)
        canvas.line(xs[0], y - row_height, xs[-1], y - row_height)
        for x in xs:
            canvas.line(x, y, x, y - row_height)
        values = headers if row_index == 0 else rows[row_index - 1]
        for index, value in enumerate(values):
            canvas.drawString(xs[index] + 2, y - 14, value)
        y -= row_height
