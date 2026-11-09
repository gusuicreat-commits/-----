"""生成毫米制、Z 轴向上的示例装配体，仅用于演示和离线测试。"""

from pathlib import Path

import cadquery as cq


def make_sample_step(output: Path | None = None) -> Path:
    output = output or Path(__file__).resolve().with_name("示例简化模型.step")
    assembly = cq.Assembly(name="示例起重机")

    def box(size: tuple[float, float, float], center: tuple[float, float, float]) -> cq.Shape:
        return cq.Workplane("XY").box(*size).translate(center).val()

    def add(name: str, boxes: list[tuple[tuple, tuple]], color: tuple, extra: list[cq.Shape] | None = None) -> None:
        shapes = [box(size, center) for size, center in boxes]
        shapes.extend(extra or [])
        assembly.add(cq.Compound.makeCompound(shapes), name=name, color=cq.Color(*color))

    steel, red, yellow = (0.875, 0.89, 0.91), (0.75, 0.22, 0.17), (0.89, 0.66, 0.17)
    add("主梁", [
        ((104000, 2600, 6500), (0, -3200, 42250)),
        ((104000, 2600, 6500), (0, 3200, 42250)),
        ((1200, 9000, 6500), (-51400, 0, 42250)),
        ((1200, 9000, 6500), (51400, 0, 42250)),
    ], steel)
    for name, x in (("刚性腿", -44000), ("柔性腿", 44000)):
        columns = [
            cq.Workplane("XY").workplane(offset=3300)
            .center(x, side * 9000).rect(2400, 2400)
            .workplane(offset=35700).center(0, -side * 5800).rect(2000, 2000)
            .loft().val()
            for side in (-1, 1)
        ]
        add(name, [
            ((2500, 22000, 2000), (x, 0, 2300)),
            ((1300, 12200, 1300), (x, 0, 21150)),
            ((2200, 2000, 1000), (x, -9000, 800)),
            ((2200, 2000, 1000), (x, 9000, 800)),
        ], steel, columns)
    add("小车", [
        ((12000, 9000, 4500), (0, 0, 47750)),
        ((7000, 5000, 1000), (0, 0, 50500)),
    ], yellow)
    add("吊钩", [((3000, 3000, 2500), (0, 0, 31850))], yellow)
    add("司机室", [((4000, 3000, 3000), (-41000, 0, 27300))], red)
    for name, x in (("轨道左", -44000), ("轨道右", 44000)):
        add(name, [((600, 22000, 300), (x, 0, 150))], (0.29, 0.31, 0.33))
    output.parent.mkdir(parents=True, exist_ok=True)
    assembly.save(str(output), exportType="STEP")
    # 产品名写为标准 Unicode 转义，避免导出器的字节编码歧义。
    text = output.read_text(encoding="utf-8")
    for name in ("示例起重机", "主梁", "刚性腿", "柔性腿", "小车", "吊钩", "司机室", "轨道左", "轨道右"):
        escaped = "\\X2\\" + name.encode("utf-16-be").hex().upper() + "\\X0\\"
        text = text.replace(name.encode("utf-8").decode("latin1"), escaped).replace(name, escaped)
    output.write_text(text, encoding="utf-8")
    return output


if __name__ == "__main__":
    print(f"已生成示例模型：{make_sample_step()}")
