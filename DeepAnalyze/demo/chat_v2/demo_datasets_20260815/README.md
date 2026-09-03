# chat_v2 演示数据

本目录包含 4 组公开数据：2 组单文件、2 组多文件。chat_v2 的“加载示例”弹窗会读取 `catalog.json`，加载所选数据源并自动填入所选问题。每个独立分析目标都是一个 question，并在各组 `questions.md` 中提供中英文版本。

| 类型 | 数据集 | 规模 | 适合演示 |
| --- | --- | ---: | --- |
| 单文件 | Palmer Penguins | 344 行，8 列 | 缺失值检查、分组比较、散点图 |
| 单文件 | 全球预期寿命 | 21,565 行，4 列 | 时间趋势、国家比较、异常年份 |
| 多文件 | UCI Bike Sharing | 日表 731 行；小时表 17,379 行 | 跨文件核对、时序与小时模式 |
| 多文件 | FiveThirtyEight College Majors | 5 个 CSV，各约 76-174 行 | 关联多个口径、就业与收入比较 |

## 使用顺序

1. 快速演示：`single_file/palmer_penguins`。
2. 时间序列演示：`single_file/life_expectancy`。
3. 多文件一致性演示：`multi_file/bike_sharing`。
4. 多文件综合分析演示：`multi_file/college_majors`。

## 来源与许可

- Palmer Penguins：<https://allisonhorst.github.io/palmerpenguins/>，数据为 CC0；原始数据由 Palmer Station LTER 与 Kristen Gorman 提供。
- 全球预期寿命：<https://ourworldindata.org/grapher/life-expectancy>，由 Our World in Data 对 Riley、Zijdeman、HMD、UN WPP 等来源进行整理；详细归属与许可见本目录的 `source_metadata.json` 和数据页。
- UCI Bike Sharing：<https://archive.ics.uci.edu/dataset/275/bike+sharing+dataset>，CC BY 4.0，引用：Fanaee-T, H. (2013), DOI 10.24432/C5W894。
- FiveThirtyEight College Majors：<https://github.com/fivethirtyeight/data/tree/master/college-majors>，数据来自 2010-2012 ACS PUMS，仓库数据许可为 CC BY 4.0。

这些文件保持上游原样，未做翻译、抽样或字段改写。分析时应注明数据年代和适用范围，尤其不要把美国历史调查数据表述为当前全球结论。
