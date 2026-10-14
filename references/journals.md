# 岩石力学领域期刊文献数据库

> 本文件是技能的期刊知识库。检索前先读此文件，用于判断主题与期刊类别的匹配度、解读评分加权、构造兜底检索 URL。
> 26 刊的 OpenAlex source ID 已内置于 `scripts/search_rock_journals.py` 的 JOURNALS 字典，维护期刊列表时同步更新该字典。
>
> **白名单定位**：默认检索为全 OpenAlex 库，26 刊仅作综合评分加分
> （A 类 +3 / B~G 类 +2 / H 类 +1，见 `lit_common.CAT_POINTS`），**不再排除白名单外文献**；
> 仅在用户要求"只要订阅刊"或指定 `--journals/--category` 时才启用硬过滤。
>
> **影响因子/JCR 分区的唯一权威来源是 [`journal_metrics.csv`](journal_metrics.csv)**，
> 每行带指标年份/来源/核验状态。本文件不再维护 IF 数值列，避免两处数字漂移；引用指标时一律取自 csv，
> 其中"待核验/待复核"条目严禁当作确定值输出给用户。

## 一、期刊总表（26 种核心源）

### A. 岩石力学核心（4 种）

| 缩写 | 全称 | ISSN | 出版商 | 主题范围 |
|------|------|------|--------|---------|
| RMRE | Rock Mechanics and Rock Engineering | 0723-2632 | Springer | 岩石力学基础理论、实验、本构、现场监测、岩爆、支护 |
| IJRMMS | International Journal of Rock Mechanics and Mining Sciences | 1365-1609 | ScienceDirect | 岩石力学与采矿科学，实验与数值方法 |
| AG | Acta Geotechnica | 1861-1133 | Springer | 岩土力学理论、计算岩土、本构模型 |
| JRMGE | Journal of Rock Mechanics and Geotechnical Engineering | 1674-7755 | ScienceDirect | 岩石力学与岩土工程综合，中国人主编旗舰刊 |

### B. 岩土工程核心（9 种）

| 缩写 | 全称 | ISSN | 出版商 | 主题范围 |
|------|------|------|--------|---------|
| CG | Computers and Geotechnics | 0266-352X | ScienceDirect | 计算岩土、数值方法、DEM/FEM |
| GGM | Geotextiles and Geomembranes | 0266-1144 | ScienceDirect | 土工合成材料 |
| GEO | Géotechnique | 0016-8505 | Emerald | 岩土力学权威刊，理论与室内试验 |
| JGGE | Journal of Geotechnical and Geoenvironmental Engineering | 1090-0241 | ASCE | 岩土工程旗舰，基础、边坡、环境岩土 |
| IJOG | International Journal of Geomechanics | 1532-3641 | ASCE | IACMAG 旗舰，岩土计算方法 |
| NAG | International Journal for Numerical and Analytical Methods in Geomechanics | 0363-9061 | Wiley | 岩土数值与分析方法 |
| CGJ | Canadian Geotechnical Journal | 0008-3674 | Canadian Science Publishing | 岩土工程综合 |
| SAF | Soils and Foundations | 0038-0806 | ScienceDirect | 日本岩土，土与岩石力学 |

### C. 工程地质与地质灾害（3 种）

| 缩写 | 全称 | ISSN | 出版商 | 主题范围 |
|------|------|------|--------|---------|
| EG | Engineering Geology | 0013-7952 | ScienceDirect | 工程地质、边坡、岩体结构 |
| — | Landslides | 1612-510X | Springer | 滑坡机理、监测、风险评估 |
| BEGE | Bulletin of Engineering Geology and the Environment | 1435-9529 | Springer | 工程地质与环境 |

### D. 地下工程与隧道（1 种）

| 缩写 | 全称 | ISSN | 出版商 | 主题范围 |
|------|------|------|--------|---------|
| TUST | Tunnelling and Underground Space Technology | 0886-7798 | ScienceDirect | 隧道与地下空间技术 |

### E. 断裂力学与动力学（2 种）

| 缩写 | 全称 | ISSN | 出版商 | 主题范围 |
|------|------|------|--------|---------|
| EFM | Engineering Fracture Mechanics | 0013-7944 | ScienceDirect | 断裂力学，含岩石断裂 |
| SDEE | Soil Dynamics and Earthquake Engineering | 0267-7261 | ScienceDirect | 土动力学与岩土地震工程 |

### F. 能源岩土力学（1 种）

| 缩写 | 全称 | ISSN | 出版商 | 主题范围 |
|------|------|------|--------|---------|
| G4 | Geomechanics and Geophysics for Geo-Energy and Geo-Resources | 2363-4357 | Springer | 地热、CO₂ 封存、地下储能、诱发地震 |

### G. 中文核心——三岩（3 种，万方收录）

| 名称 | 收录 | 主题范围 |
|------|------|---------|
| 岩石力学与工程学报 | EI/CSCD | 国内岩石力学第一刊，基础理论 + 工程应用 |
| 岩土力学 | EI/CSCD | 中科院武汉岩土所主办，基础研究 |
| 岩土工程学报 | EI/CSCD | 岩土工程权威，偏工程实践 |

### 附：其他中文期刊（4 种，万方收录）

| 名称 | 收录 | 相关方向 |
|------|------|---------|
| 土木工程学报 | EI/CSCD | 岩土工程子方向 |
| 工程地质学报 | CSCD/北大核心 | 工程地质 |
| 煤炭学报 | EI/CSCD | 深部煤炭开采 |
| 水利学报 | EI/CSCD | 水工岩土 |

## 二、按主题快速定位期刊

| 研究主题 | 优先期刊（按顺序） |
|---------|-------------------|
| 岩石本构/破坏机理 | RMRE, IJRMMS, JRMGE, AG |
| 岩爆/深部开采 | RMRE, IJRMMS, 岩石力学与工程学报, 煤炭学报 |
| 数值方法（FEM/DEM/PFC） | CG, NAG, IJOG, AG |
| 隧道/地下工程 | TUST, RMRE, 岩土力学 |
| 边坡/滑坡/地质灾害 | Landslides, EG, BEGE, 工程地质学报 |
| 岩石断裂/损伤 | EFM, RMRE, IJRMMS |
| 地热/CO₂封存/储能 | G4, JRMGE, RMRE |
| 渗流/水力耦合 | IJRMMS, CG, 岩土力学, 水利学报 |
| 地震/动力响应 | SDEE, NAG |
| 支护与加固 | RMRE, TUST, 岩石力学与工程学报 |

## 三、可扩展期刊（用户暂未订阅，检索时可按需纳入）

| 期刊 | 方向 |
|------|------|
| Geomechanics for Energy and the Environment | 地热、封存（Elsevier） |
| Journal of Geophysical Research: Solid Earth | 岩石物理 |
| Deep Underground Science and Engineering | 深地科学（新刊） |
| Géotechnique Letters | 快报类 |
| Geomechanics and Engineering | Techno Press |

默认检索为全 OpenAlex 库，白名单仅作评分加权；上表扩展期刊与 26 刊在检索范围上一视同仁，
差异只体现在评分（白名单外期刊层级分 =0）与指标核验状态（不在 `journal_metrics.csv` 覆盖内则显示"待核验"）。
用户要求"只要订阅刊"时才用 `--scope whitelist` 硬过滤。
