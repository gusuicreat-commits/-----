# 分镜正反例

## 目录
- 合格分镜
- 六处典型错误
- 逐条批注

## 合格分镜

来源：示例项目离线 plan 回放的参数与表达，补齐结构分解、参数卡并调整到 45 秒。
配套输入位于本技能 evals/fixtures/standard；所有数值为示例资料，不代表工业现场验收。
参数为已确认示例状态；模型配置、运动行程与素材元数据也为离线测试输入。
下例无 block/warn，NOT_REVIEWED 提示仍保留，因为自动测试不替代人工复核。

```json
{
  "version": 1,
  "title": "大块头，也有细功夫",
  "fps": 30,
  "width": 1920,
  "height": 1080,
  "shots": [
    {
      "id": "S1",
      "kind": "title",
      "source": "model",
      "duration_s": 4,
      "narration": "大块头，怎样稳稳托起重物？",
      "fact_refs": [],
      "analogy_refs": [],
      "asset_refs": [],
      "params": {
        "title": "大块头，也有细功夫",
        "subtitle": ""
      },
      "review": {
        "status": "pending",
        "note": ""
      },
      "narration_resolved": "大块头，怎样稳稳托起重物？"
    },
    {
      "id": "S2",
      "kind": "analogy",
      "source": "model",
      "duration_s": 8,
      "narration": "主梁长{{F_girder_length}}，{{A_girder_length_football_field}}。",
      "fact_refs": [
        "F_girder_length"
      ],
      "analogy_refs": [
        "A_girder_length_football_field"
      ],
      "asset_refs": [],
      "params": {
        "analogy": "A_girder_length_football_field"
      },
      "review": {
        "status": "pending",
        "note": ""
      },
      "narration_resolved": "主梁长104米，差不多就是一个标准足球场那么长。"
    },
    {
      "id": "S3",
      "kind": "exploded",
      "source": "model",
      "duration_s": 5,
      "narration": "主梁和支腿搭起骨架。",
      "fact_refs": [],
      "analogy_refs": [],
      "asset_refs": [],
      "params": {
        "parts": [
          "girder",
          "leg_left",
          "leg_right",
          "trolley"
        ],
        "spread_m": 12
      },
      "review": {
        "status": "pending",
        "note": ""
      },
      "narration_resolved": "主梁和支腿搭起骨架。"
    },
    {
      "id": "S4",
      "kind": "motion",
      "source": "model",
      "duration_s": 6,
      "narration": "资料列示小车速度{{F_trolley_speed}}。",
      "fact_refs": [
        "F_trolley_speed"
      ],
      "analogy_refs": [],
      "asset_refs": [],
      "params": {
        "axis": "trolley",
        "from_m": -30,
        "to_m": 30,
        "speedup": 20
      },
      "review": {
        "status": "pending",
        "note": ""
      },
      "narration_resolved": "资料列示小车速度每分钟30米。"
    },
    {
      "id": "S5",
      "kind": "weld_macro",
      "source": "model",
      "duration_s": 9,
      "narration": "焊缝错边不大于{{F_weld_tolerance}}，{{A_weld_tolerance_hair}}。",
      "fact_refs": [
        "F_weld_tolerance"
      ],
      "analogy_refs": [
        "A_weld_tolerance_hair"
      ],
      "asset_refs": [],
      "params": {
        "fact": "F_weld_tolerance",
        "analogy": "A_weld_tolerance_hair"
      },
      "review": {
        "status": "pending",
        "note": ""
      },
      "narration_resolved": "焊缝错边不大于0.5毫米，大约只有7根头发丝并排那么宽。"
    },
    {
      "id": "S6",
      "kind": "real_media",
      "source": "real",
      "duration_s": 5,
      "narration": "像这样的门机，用于船体分段吊装。",
      "fact_refs": [],
      "analogy_refs": [],
      "asset_refs": [
        "IMG_ODENSE"
      ],
      "params": {
        "asset": "IMG_ODENSE",
        "effect": "kenburns",
        "caption": "参考实拍 · 非本机"
      },
      "review": {
        "status": "pending",
        "note": ""
      },
      "narration_resolved": "像这样的门机，用于船体分段吊装。"
    },
    {
      "id": "S7",
      "kind": "data_card",
      "source": "model",
      "duration_s": 5,
      "narration": "关键参数，都有文档依据。",
      "fact_refs": [
        "F_rated_load",
        "F_span"
      ],
      "analogy_refs": [],
      "asset_refs": [],
      "params": {
        "facts": [
          "F_rated_load",
          "F_span"
        ]
      },
      "review": {
        "status": "pending",
        "note": ""
      },
      "narration_resolved": "关键参数，都有文档依据。"
    },
    {
      "id": "S8",
      "kind": "outro",
      "source": "model",
      "duration_s": 3,
      "narration": "大与精，缺一不可。",
      "fact_refs": [],
      "analogy_refs": [],
      "asset_refs": [],
      "params": {
        "title": "大与精，缺一不可",
        "subtitle": ""
      },
      "review": {
        "status": "pending",
        "note": ""
      },
      "narration_resolved": "大与精，缺一不可。"
    }
  ],
  "analogies": [
    {
      "id": "A_girder_length_football_field",
      "fact": "F_girder_length",
      "ref": "football_field",
      "axis": "length",
      "ratio": 0.99,
      "text": "差不多就是一个标准足球场那么长",
      "ref_size_m": 105.0,
      "ref_size": 105,
      "ref_unit": "m",
      "basis": "国际足联推荐比赛场地长105米",
      "formula": "104 ÷ 105 ≈ 0.99"
    },
    {
      "id": "A_weld_tolerance_hair",
      "fact": "F_weld_tolerance",
      "ref": "hair",
      "axis": "thickness",
      "ratio": 7.143,
      "text": "大约只有7根头发丝并排那么宽",
      "ref_size_m": 7.000000000000001e-05,
      "ref_size": 0.07,
      "ref_unit": "mm",
      "basis": "头发丝直径约0.07毫米",
      "formula": "0.5 ÷ 0.07 ≈ 7.14"
    }
  ]
}
```

## 六处典型错误

下例使用相同 facts/assets/project/rig，保留完整结构；六处错误含五项 block 和一项 warn。

```json
{
  "version": 1,
  "title": "大块头，也有细功夫",
  "fps": 30,
  "width": 1920,
  "height": 1080,
  "shots": [
    {
      "id": "S1",
      "kind": "title",
      "source": "model",
      "duration_s": 4,
      "narration": "它能吊起1230吨。",
      "fact_refs": [],
      "analogy_refs": [],
      "asset_refs": [],
      "params": {
        "title": "大块头，也有细功夫",
        "subtitle": ""
      },
      "review": {
        "status": "pending",
        "note": ""
      },
      "narration_resolved": "它能吊起1230吨。"
    },
    {
      "id": "S2",
      "kind": "analogy",
      "source": "model",
      "duration_s": 8,
      "narration": "主梁长{{F_missing}}。",
      "fact_refs": [
        "F_girder_length"
      ],
      "analogy_refs": [
        "A_girder_length_football_field"
      ],
      "asset_refs": [],
      "params": {
        "analogy": "A_girder_length_football_field"
      },
      "review": {
        "status": "pending",
        "note": ""
      },
      "narration_resolved": "主梁长{{F_missing}}。"
    },
    {
      "id": "S3",
      "kind": "ai_broll",
      "source": "ai",
      "duration_s": 5,
      "narration": "主梁和支腿搭起骨架。",
      "fact_refs": [],
      "analogy_refs": [],
      "asset_refs": [],
      "params": {
        "recipe": "sunrise_port",
        "palette": "warm",
        "prompt": "主梁与支腿特写"
      },
      "review": {
        "status": "pending",
        "note": ""
      },
      "narration_resolved": "主梁和支腿搭起骨架。"
    },
    {
      "id": "S4",
      "kind": "motion",
      "source": "model",
      "duration_s": 6,
      "narration": "资料列示小车速度{{F_trolley_speed}}。",
      "fact_refs": [
        "F_trolley_speed"
      ],
      "analogy_refs": [],
      "asset_refs": [],
      "params": {
        "axis": "trolley",
        "from_m": -100,
        "to_m": 30
      },
      "review": {
        "status": "pending",
        "note": ""
      },
      "narration_resolved": "资料列示小车速度每分钟30米。"
    },
    {
      "id": "S5",
      "kind": "weld_macro",
      "source": "model",
      "duration_s": 9,
      "narration": "焊缝错边不大于{{F_weld_tolerance}}，{{A_weld_tolerance_hair}}。",
      "fact_refs": [
        "F_weld_tolerance"
      ],
      "analogy_refs": [
        "A_weld_tolerance_hair"
      ],
      "asset_refs": [],
      "params": {
        "fact": "F_weld_tolerance",
        "analogy": "A_weld_tolerance_hair"
      },
      "review": {
        "status": "pending",
        "note": ""
      },
      "narration_resolved": "焊缝错边不大于0.5毫米，大约只有7根头发丝并排那么宽。"
    },
    {
      "id": "S6",
      "kind": "real_media",
      "source": "real",
      "duration_s": 5,
      "narration": "这台门机，用于船体分段吊装。",
      "fact_refs": [],
      "analogy_refs": [],
      "asset_refs": [
        "IMG_ODENSE"
      ],
      "params": {
        "asset": "IMG_ODENSE",
        "effect": "kenburns",
        "caption": "参考实拍 · 非本机"
      },
      "review": {
        "status": "pending",
        "note": ""
      },
      "narration_resolved": "这台门机，用于船体分段吊装。"
    },
    {
      "id": "S7",
      "kind": "data_card",
      "source": "model",
      "duration_s": 5,
      "narration": "关键参数关键参数，都有文档依据。",
      "fact_refs": [
        "F_rated_load",
        "F_span"
      ],
      "analogy_refs": [],
      "asset_refs": [],
      "params": {
        "facts": [
          "F_rated_load",
          "F_span"
        ]
      },
      "review": {
        "status": "pending",
        "note": ""
      },
      "narration_resolved": "关键参数关键参数，都有文档依据。"
    },
    {
      "id": "S8",
      "kind": "outro",
      "source": "model",
      "duration_s": 3,
      "narration": "大与精，缺一不可。",
      "fact_refs": [],
      "analogy_refs": [],
      "asset_refs": [],
      "params": {
        "title": "大与精，缺一不可",
        "subtitle": ""
      },
      "review": {
        "status": "pending",
        "note": ""
      },
      "narration_resolved": "大与精，缺一不可。"
    }
  ],
  "analogies": [
    {
      "id": "A_girder_length_football_field",
      "fact": "F_girder_length",
      "ref": "football_field",
      "axis": "length",
      "ratio": 0.99,
      "text": "差不多就是一个标准足球场那么长",
      "ref_size_m": 105.0,
      "ref_size": 105,
      "ref_unit": "m",
      "basis": "国际足联推荐比赛场地长105米",
      "formula": "104 ÷ 105 ≈ 0.99"
    },
    {
      "id": "A_weld_tolerance_hair",
      "fact": "F_weld_tolerance",
      "ref": "hair",
      "axis": "thickness",
      "ratio": 7.143,
      "text": "大约只有7根头发丝并排那么宽",
      "ref_size_m": 7.000000000000001e-05,
      "ref_size": 0.07,
      "ref_unit": "mm",
      "basis": "头发丝直径约0.07毫米",
      "formula": "0.5 ÷ 0.07 ≈ 7.14"
    }
  ]
}
```

## 逐条批注

| 镜头/字段 | 校验码 | 具体修法 |
|---|---|---|
| S1.narration | UNSOURCED_NUMBER / block | 用 {{F_rated_load}} 替换 1230吨，并把 F_rated_load 加入 fact_refs。 |
| S2.narration | UNKNOWN_FACT / block | 将 F_missing 改为 F_girder_length，恢复对应事实引用。 |
| S3.params.prompt | AI_SHOWS_EQUIPMENT / block | 需要结构就恢复 exploded/source=model 与对应 params；若只要转场，改为海面光影描述。 |
| S4.params.from_m | MOTION_OUT_OF_RANGE / block | 将 -100 改为真实行程 [-38,38] 内值，例如 -30，再重新计算倍速。 |
| S6.narration | REFERENCE_ASSET_CLAIM / warn | 把“这台门机”改为“像这样的门机”；不能改素材 provenance 绕过。 |
| S7.narration | DUPLICATE_PHRASE / block | 删掉第二个“关键参数”，保留原有人工语气。 |

保留 NOT_REVIEWED 提示；六处典型错误不含正常的人工复核提示。
