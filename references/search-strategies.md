# 检索策略与工具手册（网络检索兜底方案）

> **注意**：本手册的网络检索方案是**兜底路径（最后手段）**。仅在全部可用数据源（OpenAlex / CrossRef / Semantic Scholar）都被证实不可用、且结果仍不足时，**并取得用户明确许可后**才可使用。禁止未经用户应允擅自 WebSearch / WebFetch。
> 包含：出版商检索 URL 模板、中英术语对照表、WebSearch 域名过滤配置、输出模板。

## 一、各出版商检索 URL 模板

### 1. ScienceDirect (Elsevier) — 按期刊过滤

```
https://www.sciencedirect.com/search?qs={关键词}&pub={ISSN无连字符}&show=25
```

示例：在 IJRMMS 中检索 rockburst：
`https://www.sciencedirect.com/search?qs=rockburst&pub=13651609&show=25`

不限定期刊（跨 Elsevier 刊）：`https://www.sciencedirect.com/search?qs={关键词}`

注意：ScienceDirect 对程序化访问有 Cloudflare 防护，WebFetch 可能失败。失败时改用 WebSearch + 域名过滤。

### 2. Springer — 按期刊过滤

```
https://link.springer.com/search?query={关键词}&search-within=Journal&facet-journal-id={journalID}
```

journalID 对照：RMRE=603，AG=11440，Landslides=10346，BEGE=10064，G4=40948。

Springer 对 WebFetch 通常友好，优先尝试。

### 3. Wiley

```
https://onlinelibrary.wiley.com/action/doSearch?AllField={关键词}&SeriesKey=10969853
```

（SeriesKey 为期刊 eISSN，目前只有 NAG 一种 Wiley 刊。）Wiley 有访问防护，失败则改用 WebSearch。

### 4. ASCE — 按期刊过滤

```
https://ascelibrary.org/action/doSearch?AllField={关键词}&SeriesKey={journalCode}
```

journalCode 对照：JGGE=jggefk，IJOG=ijgnai。

### 5. Emerald（Géotechnique）

Emerald 对程序化访问有 403 防护，不要直接 WebFetch 检索页。改用 WebSearch 限定 `emerald.com` 域名，或建议用户手动浏览 https://www.emerald.com/jgeot 。

### 6. 万方数据（中文期刊）

```
https://s.wanfangdata.com.cn/paper?q={关键词} 期刊名:"岩石力学与工程学报"
```

万方检索可用 WebSearch 限定 `wanfangdata.com.cn` 域名替代。中文文献也可用通用搜索引擎 + 期刊名关键词组合。

## 二、WebSearch 域名过滤配置

按出版商分组的域名白名单，用于 WebSearch 的 allowed_domains：

- **Elsevier 刊**：`sciencedirect.com`, `doi.org`
- **Springer 刊**：`link.springer.com`, `springer.com`
- **Wiley 刊**：`onlinelibrary.wiley.com`
- **ASCE 刊**：`ascelibrary.org`
- **中文刊**：`wanfangdata.com.cn`, `cnki.net`

推荐检索式：`{英文关键词} {期刊名或缩写}` 或 `{中文关键词} {期刊名}`。
多轮检索时按"核心 4 刊 → 高相关类别 → 中文三岩"顺序分批执行，每批 2-3 个查询。

## 三、岩石力学中英术语对照表

检索前把用户中文主题翻译为标准英文术语，组合使用提高查全率：

| 中文 | 英文（优先） | 英文（备选） |
|------|-------------|-------------|
| 岩爆 | rockburst | rock burst |
| 深部岩体/深部开采 | deep rock mass / deep mining | high geo-stress, high in-situ stress |
| 岩石本构模型 | constitutive model | rock constitutive relation |
| 破坏机理 | failure mechanism | failure behaviour |
| 裂隙岩体 | fractured rock mass | jointed rock mass |
| 节理 | rock joint | joint, discontinuity |
| 渗流 | seepage | fluid flow in rock |
| 水-力耦合 | hydro-mechanical coupling | HM coupling, hydromechanics |
| 三轴试验 | triaxial test | triaxial compression |
| 单轴抗压强度 | uniaxial compressive strength | UCS |
| 巴西劈裂 | Brazilian splitting test | indirect tensile strength |
| 断裂韧度 | fracture toughness | rock fracture |
| 蠕变 | creep | time-dependent behaviour |
| 损伤 | damage | damage evolution |
| 锚杆支护 | rockbolt support | rock reinforcement |
| 喷锚支护 | shotcrete and bolting | — |
| 隧道围岩 | surrounding rock / tunnel lining | — |
| 边坡稳定性 | slope stability | — |
| 数值模拟 | numerical simulation | FLAC3D, PFC, UDEC, DDA |
| 离散元 | discrete element method | DEM |
| 岩体分级 | rock mass classification | RMR, Q-system, GSI |
| 地应力 | in-situ stress | geostress, initial stress |
| 微震监测 | microseismic monitoring | acoustic emission |
| 岩石物理 | rock physics | — |
| 卸荷 | unloading | excavation unloading |
| 冻融 | freeze-thaw | frost damage |
| 动力扰动/爆破 | dynamic disturbance / blasting | — |
| 岩石声发射 | acoustic emission | AE |
| 真三轴 | true triaxial | polyaxial |
| 渗透率 | permeability | hydraulic conductivity |
| 有效应力 | effective stress | — |
| 应力路径 | stress path | — |
| 尺度效应 | scale effect | size effect |
| 各向异性 | anisotropy | transversely isotropic |

组合策略：主题词 + 方法词（如 "rockburst" + "machine learning"）、主题词 + 对象词（如 "creep" + "salt rock"）。

## 四、输出模板

检索结果按以下 Markdown 表格输出（相关性从高到低排序）：

```markdown
## 检索结果：{主题}（{检索日期}）

**检索式**：{实际使用的关键词组合与渠道}

| # | 标题 | 作者 | 年份 | 期刊 | DOI/链接 | 相关性 |
|---|------|------|------|------|---------|--------|
| 1 | ... | ... | ... | IJRMMS | ... | ★★★ |

### 重点文献摘要
> **[1] 标题**（期刊, 年份）
> 一句话概括方法与结论，以及与用户主题的关联点。

### 覆盖情况说明
- 已覆盖期刊：{列表}
- 未覆盖/建议扩展：{原因}
```

相关性评级标准：
- ★★★：主题直接相关，方法或对象与用户问题高度匹配
- ★★：同领域，有参考价值
- ★：背景/外围文献

硬性要求：
1. 只收录 26 种核心源（含中文附刊）的文章；扩展期刊须单独注明。
2. 每条必须给可核实的 DOI 或链接，不确定的信息标注"待核实"，禁止编造。
3. 中文文献标题保持中文，期刊名用中文；英文文献保持英文原文。
4. 单次检索默认输出 10-20 条，用户要求综述时可扩展并分类组织。

## 五、轮询迭代检索经验（多源实测积累：含水率×岩爆）

> 下述实测漏斗数据与术语迭代路径为应用过程中沉淀（详见 `../CHANGELOG.md` 对应日期记录），仅作策略参考，非限定时间刻度。

**实测漏斗**：三轮 21 组词 → 454 命中 → 270 去重 → 14 候选 → 人工复核 10 篇高质量。第一轮 8 组词仅得 9 篇严格相关，验证交叉主题必须多轮。

**术语迭代路径**（本次实例）：
- 初始设计：water content / moisture / saturation × rockburst / bursting liability
- 轮次 2 学到：water injection pressure relief（注水卸压）、impact propensity、water-rich
- 轮次 3 学到：weakening mechanism of water（介词短语变体，精确词组匹配不到）

**关键技巧**：
1. "water" 一词用泛匹配 + 排除清单，不要用精确词组（会漏 "weakening mechanism of water on rockbursts"）
2. OpenAlex 部分文献无摘要（尤其 TUST/EFM 新文章），必须保留"标题双命中"通道兜底
3. 假阳性三大类：引水/输水隧洞（工程背景）、水力压裂/渗流（相邻领域）、摘要偶然提及（T/a 双信号区分）
4. 中文期刊命中后摘要常缺失，标题是唯一可靠信号

## 六、轮询迭代检索经验（含水率×岩爆实验，A/G/H 共 11 刊）

**实测漏斗**：三轮共 22 组词 → 轮1: 166→118去重→9 相关；轮2: 93→85→**0**；轮3(词组引号): 45→35→1。最终核心 6 篇 + 背景 3 篇。

**新教训**：
1. **B 侧词表必须覆盖国际刊术语变体**：`proneness`、连写 `strainburst`、复数 `bursts`、`burst tendency/potential`——默认词表缺这些会导致漏检（iterative_search.py 默认词表已含这些变体）。
2. **固定术语用引号词组查询**：OpenAlex 多词检索是词袋 OR 语义，`impact tendency water coal` 会召回焦化废水选煤等噪声；`"bursting liability" water` 显著降噪。
3. **白名单交集可能天然很小**：水-岩爆实验的经典文献大量发表在 26 刊之外（Int. J. Mining Science & Technology、煤炭科学技术等）。收敛后若核心集 <5 篇且用户需要综述级覆盖，应主动建议扩展期刊范围并单独注明。
4. 假阳性新亚型：**"防治措施类"文献**（注水卸压、微波致裂、充填开采）摘要含岩爆+水但主题是工程措施而非"含水率对岩爆的影响机理"，按用户意图决定取舍并在输出中标注分级。
