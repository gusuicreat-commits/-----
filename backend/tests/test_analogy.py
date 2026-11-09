import pytest

from app.agent.analogy import compute
from app.agent.text import find_unsourced_numbers, format_value, resolve


@pytest.mark.parametrize("ref,axis,value,unit,ratio,expected", [
    ("football_field", "length", 104, "m", .99, "差不多就是一个标准足球场那么长"),
    ("boeing747", "length", 64.4, "m", 1, "差不多和波音747的翼展一样宽"),
    ("building_floor", "height", 51, "m", 17, "相当于17层楼那么高"),
    ("bus", "length", 104, "m", 8.667, "相当于8.7辆12米长的公交车"),
    ("bus", "length", 240, "m", 20, "相当于20辆12米长的公交车"),
    ("person", "height", 51, "m", 29.143, "相当于29个成年人"),
    ("person", "height", 3.5, "m", 2, "相当于2.0个成年人"),
    ("car", "mass", 1230, "t", 820, "相当于820辆小轿车的重量"),
    ("elephant", "mass", 1230, "t", 205, "相当于205头成年非洲象的重量"),
    ("hair", "thickness", .5, "mm", 7.143, "大约只有7根头发丝并排那么宽"),
    ("hair", "thickness", .01, "mm", .143, "还不到一根头发丝粗"),
    ("hair", "thickness", .0005, "m", 7.143, "大约只有7根头发丝并排那么宽"),
    ("football_field", "length", 104000, "mm", .99, "差不多就是一个标准足球场那么长"),
    ("football_field", "length", 210, "m", 2, "相当于2.0标准足球场"),
])
def test_compute(ref, axis, value, unit, ratio, expected):
    result = compute("A_test", {"id": "F_test", "value": value, "unit": unit}, ref, axis)
    assert result["ratio"] == ratio
    assert result["text"] == expected
    assert result["fact"] == "F_test" and result["id"] == "A_test"
    assert result["basis"] and " ÷ " in result["formula"]
    if ref == "football_field":
        assert result["ref_size_m"] == 105
        if value in (104, 104000):
            assert result["formula"] == "104 ÷ 105 ≈ 0.99"
    if ref == "hair":
        assert result["ref_size_m"] == .07
    if ref == "car":
        assert result["ref_size_m"] == 1.5


@pytest.mark.parametrize("ref,axis,unit,value", [
    ("car", "length", "m", 100), ("missing", "length", "m", 1),
    ("bus", "length", "t", 1), ("bus", "length", "km", 1),
    ("hair", "thickness", "mm", -1), ("hair", "thickness", "mm", float("inf")),
])
def test_invalid_analogy(ref, axis, unit, value):
    with pytest.raises(ValueError):
        compute("A_bad", {"id": "F_bad", "value": value, "unit": unit}, ref, axis)


@pytest.mark.parametrize("value,unit,expected", [
    (104, "m", "104米"), (.5, "mm", "0.5毫米"), (8, "m/min", "每分钟8米"),
    (1230.0, "t", "1230吨"), (64, "个", "64个"), (100, "%", "100%"), (.25, "未知", "0.25未知"),
])
def test_format(value, unit, expected):
    assert format_value(value, unit) == expected


def test_resolve():
    assert resolve("长{{F_x}}，{{A_x}}；{{F_missing}}/{{A_missing}}", {"F_x": {"value": 104, "unit": "m"}},
                   {"A_x": {"text": "差不多就是一个标准足球场那么长"}}) == (
                       "长104米，差不多就是一个标准足球场那么长；{{F_missing}}/{{A_missing}}")


@pytest.mark.parametrize("text,expected", [
    ("长104米", ["104"]), ("精度0.5毫米", ["0.5"]), ("波音747", ["747"]),
    ("第2步", ["2"]), ("三十米", ["三十米"]), ("零点五毫米", ["零点五毫米"]),
    ("两千吨", ["两千吨"]), ("一公里", ["一公里"]), ("三千米", ["三千米"]),
    ("三厘米", ["三厘米"]), ("十秒", ["十秒"]), ("五分钟", ["五分钟"]),
    ("两小时", ["两小时"]), ("十七层", ["十七层"]), ("两倍", ["两倍"]),
    ("三辆车", ["三辆"]), ("七根头发丝", ["七根"]), ("一头象", ["一头"]),
    ("千吨位", ["千吨位"]), ("一个足球场", ["一个足球场"]),
    ("百年", ["百年"]), ("三天", ["三天"]), ("三成", ["三成"]), ("五%", ["五%"]),
    ("〇点五毫米", ["〇点五毫米"]), ("一台设备", []), ("两个部件", []),
    ("一座桥", []), ("一条线", []), ("一根绳", []), ("两辆车", []),
    ("一块板", []), ("一种方式", []), ("一次移动", []), ("一下", []),
    ("一样", []), ("一边", []), ("一点", []), ("第一", []), ("其中之一", []),
    ("一起一直一定统一唯一万一", []), ("一台三十米高的设备", ["三十米"]),
    ("三十米与0.5毫米", ["三十米", "0.5"]), ("一根毫米刻度线", ["一根"]),
])
def test_number_rules(text, expected):
    assert find_unsourced_numbers(text) == expected
