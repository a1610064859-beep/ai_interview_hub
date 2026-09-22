# 报告页数据映射与视觉实施规格（T7-R0）

| 项 | 值 |
| --- | --- |
| 状态 | **草案 v1，待指挥官 Astra 审查与队长批准** |
| 任务代号 | [T7-R0] 报告页数据映射与视觉实施规格 |
| 执行分支 | `feature/T7-report-spec` |
| 独立 Worktree | `E:\ai_interview_hub_report_spec` |
| 基线提交 | `fdd74a1`（main 当前最新头，已合入 T4、T5 预检与 T7 规格） |
| 下游任务 | T7-R1（报告页前端实现）、T7-G1（成长追踪实现）、T10（HMI 最终调优） |

---

## 1. 目标与设计原则

面向智能汽车产业岗位定向面试，报告页是学生查看多维可解释评价、复盘作答证据的核心载体，也是大赛演示视频的**第一视觉主画面**（AGENTS.md §2、§9）。

### 核心原则
1. **真实数据驱动，严禁捏造与伪造**：所有展示数据严格来自后端真实接口 `GET /api/reports/{sid}`，不编造不存在的接口与字段。
2. **缺失值与文本模式严肃可解释**：
   - 文本模式下 `expression_fluency.score` 为 `null`，页面必须明确标注“未评估”，**绝对禁止显示为 0 分**；
   - 雷达图不得将 `null` 维度作为 0 分绘制；若有效维度不足 3 个，必须优雅降级为线性仪表，不得呈现畸变多边形；
   - 考官评价原话引用（`evidence`）必须醒目呈现，体现“基于原话事实”的可解释性护城河。
3. **虚拟座舱 HMI 视觉风格**：全屏深色智能汽车座舱风（HUD 风格、系统青蓝+座舱橙 강조色、发光描边、毛玻璃微质感），彻底规避普通后台管理系统或低质问卷模板质感。
4. **零越界与严格依赖控制**：图表使用已批准的 `echarts`，不引入任何未批准的新第三方库。

---

## 2. 后端真实契约基线 (Single Source of Truth)

基于当前 `server/api/reports.py` 与 `server/schemas.py` 的已合入实现 `[已验证]`：

### 2.1 接口端点与参数
- **请求方法**：`GET`
- **请求路径**：`/api/reports/{sid}`
- **路径参数**：`sid: int`（会话正整数 ID，FastAPI 校验 `ge=1`）
- **鉴权/Cookie**：无（本地/局域网演示形态）

### 2.2 成功响应结构 (200 OK)
```json
{
  "id": 1,
  "session_id": 1,
  "job_title": "智驾测试",
  "overall": 85.7,
  "dimensions": {
    "professional_match": {
      "score": 89.0,
      "evidence": "使用CANoe分析报文",
      "reason": "熟练掌握总线通信分析工具"
    },
    "logic_structure": {
      "score": 83.0,
      "evidence": "分析报文时间戳",
      "reason": "回答具备清晰的技术排查时序逻辑"
    },
    "expression_fluency": {
      "score": null,
      "evidence": null,
      "reason": "文本模式，未评估语音流畅度"
    },
    "job_competence": {
      "score": 85.0,
      "evidence": "具备极强的安全底线意识",
      "reason": "对智驾安全红线具备高度敏感度"
    }
  },
  "highlights": [
    "工具链使用经验契合度高",
    "回答逻辑层次分明"
  ],
  "concerns": [
    "针对突发网络丢包的边缘场景排查深度略显不足"
  ],
  "improvement": [
    "建议强化车载以太网 SOME/IP 与 DoIP 异常注入测试的实操总结",
    "在回答中多采用 STAR 法则强化行动（Action）与结果（Result）的数据量化"
  ]
}
```

### 2.3 字段类型与可空语义说明
| 字段路径 | TypeScript 类型 | 允许 Null | 语义说明与取值约束 |
| :--- | :--- | :---: | :--- |
| `id` | `number` | 否 | 报告唯一 ID（正整数） |
| `session_id` | `number` | 否 | 所属面试会话 ID（正整数） |
| `job_title` | `string` | 否 | 岗位名称（如“智驾测试”、“三电系统工程师”），后端默认“未知岗位”兜底 |
| `overall` | `number \| null` | **是** | 综合评分（0.0–100.0），保留一位小数；当所有有效维度均缺失时为 `null` |
| `dimensions` | `Record<string, DimensionScore>` | 否 | 固定包含 4 个键的字典对象 |
| `dimensions.professional_match` | `DimensionScore` | 否 | 专业匹配度维度评定 |
| `dimensions.logic_structure` | `DimensionScore` | 否 | 逻辑结构维度评定 |
| `dimensions.expression_fluency` | `DimensionScore` | 否 | 表达流畅度维度评定（文本模式下 score=null, evidence=null） |
| `dimensions.job_competence` | `DimensionScore` | 否 | 岗位素养维度评定 |
| `DimensionScore.score` | `number \| null` | **是** | 单维得分（0.0–100.0，1位小数）。校验未通过或未评估时为 `null` |
| `DimensionScore.evidence` | `string \| null` | **是** | 候选人作答原文引用（1–25字字面子串）。缺失/未评估时为 `null` |
| `DimensionScore.reason` | `string` | 否 | 考官判词或缺失原因说明（如“文本模式，未评估语音流畅度”） |
| `highlights` | `string[]` | 否 | 作答优势与能力亮点列表（无亮点时返回 `[]`，不为 null） |
| `concerns` | `string[]` | 否 | 作答薄弱点与顾虑列表（无顾虑时返回 `[]`，不为 null） |
| `improvement` | `string[]` | 否 | 针对性训练与能力改进建议清单（无建议时返回 `[]`，不为 null） |

### 2.4 异常响应与业务错误码结构
HTTP 状态码严格遵照 §8.1 规范：
1. **404 SESSION_NOT_FOUND**：
   ```json
   {
     "detail": {
       "code": "SESSION_NOT_FOUND",
       "message": "面试会话不存在"
     }
   }
   ```
2. **404 REPORT_NOT_FOUND**：
   ```json
   {
     "detail": {
       "code": "REPORT_NOT_FOUND",
       "message": "报告尚未生成"
     }
   }
   ```
3. **422 Validation Error**（FastAPI 默认校验失败，如 `sid <= 0` 或非法字符）：
   ```json
   {
     "detail": [
       {
         "loc": ["path", "sid"],
         "msg": "Input should be greater than or equal to 1",
         "type": "greater_than_equal"
       }
     ]
   }
   ```
4. **网络/网关异常 (Fetch Error / 5xx)**：前端捕获网络断开、超时或服务端 500 异常。

---

## 3. 前端逐字段组件映射矩阵

| 数据字段 | 对应 UI 区域 / 组件 | 展示形式 | 空值 / 特殊状态处理 |
| :--- | :--- | :--- | :--- |
| `job_title` | 顶部状态栏 Header | 发光 Badge 胶囊：“智驾测试 · 模拟面试能力评估” | 默认显示“未知岗位” |
| `session_id`, `id` | 顶部元信息 Meta Bar | 弱化座舱灰标签：“会话编号 #1 · 报告编号 #1” | 始终存在 |
| `overall` | 主仪表舱 Hero Panel (左侧) | 120px 环形进度仪表盘（SVG Ring）+ 48px 大数字 + 评级标签（卓越/良好/及格/待提升） | 若为 `null`：大数字显示 `--`，环形进度为空灰，标注“综合分待评” |
| `dimensions` (集合) | 主仪表舱 Hero Panel (右侧) | ECharts 动态座舱雷达图（见 §5） | 仅消费有效维度；有效维度 < 3 时降级为“座舱线性仪表” |
| `dimensions[key].score` | 维度详情卡片 Grid | 独立卡片标题右侧微型进度条 + 分数（如“89.0 分”） | 若为 `null`：显示深灰标签 **“未评估”**，**禁止显示 0 分** |
| `dimensions[key].evidence` | 维度详情卡片内部 | **黑匣子原话证据卡**：带高亮双引号与青蓝描边，标注 `[考官引用]` | 若为 `null`：显示淡灰提示“本维度无直接字面引用”或隐藏引用条 |
| `dimensions[key].reason` | 维度详情卡片内部 | 考官评语文本块（14px，行高 1.6，座舱青灰渐变文字） | 始终显示后端返回的判词或原因字符串 |
| `highlights` | 深度诊断区 Insights Zone (左栏) | 翠绿（Emerald）高亮卡片列表，带 Check 徽标 | 空列表时显示座舱空状态：“未检测到突出亮点” |
| `concerns` | 深度诊断区 Insights Zone (中栏) | 琥珀橙（Amber）警示卡片列表，带 Alert 三角徽标 | 空列表时显示座舱空状态：“暂无显著能力顾虑” |
| `improvement` | 行动规划区 Action Zone (右栏) | 系统蓝（Cyan）带序号指引卡片（步骤 01, 02） | 空列表时显示“暂无建议，保持当前水平” |
| 交互入口：再次训练 | 底部操作条 Footer Action | 主操作按钮（深蓝底色 + 青蓝发光描边） | 点击跳转 `/` 重新开始面试 |
| 交互入口：成长记录 | 底部操作条 Footer Action | 次操作按钮（深灰底色 + 细描边），预留跳转 `/growth` | 当前阶段占位提示：“成长轨迹已归档，前往成长追踪” |

---

## 4. 文本模式与 Null 维度的核心呈现规约

### 4.1 表达流畅度（expression_fluency）的文本模式规则
1. **明确文案**：卡片分数位置渲染为 `[未评估]` 胶囊标签（深灰背景 `bg-slate-800`，白灰文字 `text-slate-400`）。
2. **原因呈现**：卡片正文如实展示后端的 `reason`（即：“文本模式，未评估语音流畅度”）。
3. **声学占位说明**：卡片底部带微弱提示文字：“语音闭环版本（M2）将接入语速、停顿与填充词声学量化分析”。
4. **不得补零**：**绝对不得将未评估维度渲染为 0 分**，不得给出“表达极差”或挂红报警的错误引导。

### 4.2 雷达图对于 Null 维度的数学与视觉降级策略
雷达图依赖多边形封闭几何，**2 点成线，1 点成点**，多边形雷达至少需要 **3 个有效顶点**：

```
[全部 4 维有效] (语音模式)      [3 维有效 / 1 维 Null] (M1 文本模式)    [有效维度 < 3] (部分或全 Null)
       专业匹配度                              专业匹配度                      ┌─────────────────────────┐
         /   \                                   /   \                         │   座舱雷达校准中         │
 岗位素养 ───── 逻辑结构                岗位素养 ───── 逻辑结构                 │   有效维度不足 3 项      │
         \   /                                                                 │   已切换为线性仪表对比态 │
       表达流畅度                       (动态退化为 3 轴三角形雷达)              └─────────────────────────┘
   (标准 4 轴四边形)                   (严格剔除 null 轴，不画 0 分)             (隐藏雷达图，显示线性 Bar Gauge)
```

1. **情形 1：4 个维度均有效（score !== null）**：
   - 渲染标准 4 轴星形雷达（专业匹配度、逻辑结构、表达流畅度、岗位素养）。
2. **情形 2：恰好 3 个维度有效（M1 文本模式典型状态：流畅度 null）**：
   - **动态剔除无效维度轴**，构造 3 轴三角形雷达图（指标轴仅保留专业匹配度、逻辑结构、岗位素养，max=100）。
   - **严禁保留流畅度轴并填 0 分**（填 0 分会导致雷达图塌缩成畸形尖角，误导评审认为表达分为零）。
   - 雷达图外框右上角标注小号提示：`模式降级: 文本模式仅绘制 3 项有效维度`。
3. **情形 3：有效维度 < 3 个（例如只有 2 个、1 个或 0 个有效分数）**：
   - **完全隐藏 ECharts 雷达容器**，防止渲染出无法理解的一维线段或单点。
   - 切换为 **“座舱多维线性比对仪 (Linear Bar Gauges)”** 降级组件：
     - 垂直堆叠 4 个横向进度槽；
     - 有效维度展示进度与数值（如 `85.0%`）；
     - 无效维度槽位显示虚线线框与“未评估 / 校验未通过”文案。

---

## 5. ECharts 雷达图转换逻辑与配置规格 (零新增依赖)

本实现直接使用已批准的 `echarts`（精准锁定版本 `5.6.0`）原生接口，利用 React `useEffect` + `useRef` 挂载，不引入 `echarts-for-react` 等未批准第三方包。

### 5.1 数据转换算法 (`web/lib/report-data.ts`)

为使 Node 22.22+ 原生测试运行器无需 JSX 转译即可直接导入测试，本算法与核心类型统一定义在独立纯逻辑模块 `web/lib/report-data.ts` 中，供页面组件 `web/app/reports/[sid]/page.tsx` 与单元测试 `web/tests/report.test.ts` 共同导入，避免在测试中复制代码。
```typescript
interface DimensionData {
  score: number | null;
  evidence: string | null;
  reason: string;
}

interface RadarTransformResult {
  canRenderRadar: boolean;
  radarOptions: echarts.EChartsOption | null;
  validCount: number;
}

const DIMENSION_LABEL_MAP: Record<string, string> = {
  professional_match: "专业匹配度",
  logic_structure: "逻辑结构",
  expression_fluency: "表达流畅度",
  job_competence: "岗位素养",
};

export function transformDimensionsToRadar(
  dimensions: Record<string, DimensionData>
): RadarTransformResult {
  const dimKeys = [
    "professional_match",
    "logic_structure",
    "expression_fluency",
    "job_competence",
  ];

  // 1. 严格过滤有效维度 (score !== null 且 typeof number)
  const validDims = dimKeys.filter((key) => {
    const d = dimensions[key];
    return d && typeof d.score === "number" && !isNaN(d.score);
  });

  const validCount = validDims.length;

  // 2. 少于 3 个有效点无法构成稳定闭合多边形，触发优雅降级
  if (validCount < 3) {
    return {
      canRenderRadar: false,
      radarOptions: null,
      validCount,
    };
  }

  // 3. 构建动态雷达轴指示器 (Indicators) 与对应数值向量
  const indicators = validDims.map((key) => ({
    name: DIMENSION_LABEL_MAP[key],
    max: 100,
    min: 0,
    color: "#94A3B8", // slate-400
  }));

  const values = validDims.map((key) => dimensions[key].score as number);

  // 4. HMI 座舱调色配置
  const radarOptions: echarts.EChartsOption = {
    backgroundColor: "transparent",
    tooltip: {
      trigger: "item",
      backgroundColor: "rgba(15, 23, 42, 0.9)",
      borderColor: "rgba(6, 182, 212, 0.4)",
      textStyle: { color: "#F8FAFC" },
    },
    radar: {
      indicator: indicators,
      shape: "polygon",
      splitNumber: 4,
      axisName: {
        color: "#94A3B8",
        fontSize: 12,
        fontWeight: "bold",
      },
      splitLine: {
        lineStyle: {
          color: "rgba(51, 65, 85, 0.5)", // slate-700/50
        },
      },
      splitArea: {
        show: true,
        areaStyle: {
          color: [
            "rgba(15, 23, 42, 0.4)",
            "rgba(30, 41, 59, 0.4)",
            "rgba(15, 23, 42, 0.4)",
            "rgba(30, 41, 59, 0.6)",
          ],
        },
      },
      axisLine: {
        lineStyle: {
          color: "rgba(51, 65, 85, 0.6)",
        },
      },
    },
    series: [
      {
        name: "能力雷达",
        type: "radar",
        data: [
          {
            value: values,
            name: "本次评估得分",
            symbol: "circle",
            symbolSize: 6,
            itemStyle: {
              color: "#06B6D4", // cyan-500
              borderColor: "#FFFFFF",
              borderWidth: 1.5,
            },
            lineStyle: {
              color: "#06B6D4",
              width: 2.5,
              shadowColor: "rgba(6, 182, 212, 0.5)",
              shadowBlur: 10,
            },
            areaStyle: {
              color: new echarts.graphic.RadialGradient(0.5, 0.5, 1, [
                { offset: 0, color: "rgba(6, 182, 212, 0.4)" },
                { offset: 1, color: "rgba(6, 182, 212, 0.05)" },
              ]),
            },
          },
        ],
      },
    ],
  };

  return {
    canRenderRadar: true,
    radarOptions,
    validCount,
  };
}
```

---

## 6. 视觉设计系统与座舱 HMI 规格 (Tailwind 映射)

严格遵循“全屏深色座舱风，参考智能汽车 HMI，系统蓝+橙强调色，卡片圆角发光描边”（AGENTS.md §9）。**禁止引入数字人形象、3D 引擎或任何范围外功能**。

### 6.1 调色板系统 (Color Palette)
| 角色 | 颜色值 | Tailwind 类名 | 用途 |
| :--- | :--- | :--- | :--- |
| **座舱底色** | `#080C14` | `bg-[#080C14]` | 全局视口背景，沉浸式深空座舱底色 |
| **面板底色** | `rgba(15, 23, 42, 0.75)` | `bg-slate-900/75` | 卡片主体背景，结合 `backdrop-blur-md` |
| **系统科技蓝 (主色)** | `#06B6D4` / `#0284C7` | `text-cyan-400`, `border-cyan-500` | 进度条、雷达网、按钮、高亮强调 |
| **警示/座舱橙 (副色)** | `#F97316` | `text-orange-400`, `border-orange-500` | 顾虑卡片、警示标签、追问标记 |
| **亮点翡翠绿** | `#10B981` | `text-emerald-400`, `bg-emerald-950/30` | 亮点卡片、90分以上卓越指标 |
| **微光描边** | `rgba(6, 182, 212, 0.2)` | `border border-cyan-500/20` | 座舱卡片边框，鼠标悬停亮起 |
| **主文字** | `#F8FAFC` | `text-slate-50` | 大数字、主要标题、评分结论 |
| **判词次级字** | `#94A3B8` | `text-slate-400` | 原因解释、指标说明、副标签 |

### 6.2 间距与布局断点
- **桌面端主构图 (Desktop First，适配 1920x1080 演示环境)**：
  - 容器：`max-w-7xl mx-auto px-6 py-6`；
  - 垂直无纵向过度拉伸，主视区在 1080p 屏幕下 1-2 屏内可完整总览；
  - 禁止出现水平横向滚动条（`overflow-x-hidden`）。
- **响应式断点**：
  - `lg (>= 1024px)`：Hero 区左右双栏（4:6 分割）；诊断建议区 3 栏并排；
  - `md (< 1024px)`：Hero 区单列自适应堆叠；四维卡片 2x2 网格；
  - `sm (< 640px)`：完全单列滚动流畅排列。

### 6.3 页面信息流构图图解
```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Header: [智驾未来·面试仓] 岗位: [智驾测试] (模式: 文本模拟)       [再次训练] [成长历史] │
├──────────────────────────────────────┬──────────────────────────────────────┤
│ Overall 核心仪表 (40% 宽)             │ 多维能力雷达舱 (60% 宽)               │
│   ╭─────────╮                        │                                      │
│  │   85.7    │  综合评定: [良好]      │       ECharts 动态自适应雷达图        │
│   ╰─────────╯                        │    (文本模式自适应为 3 轴三角形)     │
│   "专业匹配优异，逻辑排查严谨"        │                                      │
├──────────────────────────────────────┴──────────────────────────────────────┤
│ 四维能力证据卡片阵列 (2x2 Grid)                                             │
│ ┌─────────────────────────┐ ┌─────────────────────────┐                     │
│ │ 专业匹配度: 89.0 分     │ │ 逻辑结构: 83.0 分       │                     │
│ │ 证据: "使用CANoe分析报文"│ │ 证据: "分析报文时间戳"   │                     │
│ │ 考官判词: 熟练掌握工具  │ │ 考官判词: 排查时序分明   │                     │
│ └─────────────────────────┘ └─────────────────────────┘                     │
│ ┌─────────────────────────┐ ┌─────────────────────────┐                     │
│ │ 表达流畅度: [未评估]    │ │ 岗位素养: 85.0 分       │                     │
│ │ 证据: [文本模式无原话]  │ │ 证据: "具备安全底线意识" │                     │
│ │ 说明: 文本模式未评估语音│ │ 考官判词: 安全敏感度高   │                     │
│ └─────────────────────────┘ └─────────────────────────┘                     │
├─────────────────────────────────────────────────────────────────────────────┤
│ 深度洞察与改进清单 (3 栏并列 Grid)                                          │
│ ┌───────────────────┐ ┌───────────────────┐ ┌─────────────────────────────┐ │
│ │ 优势亮点 (Green)  │ │ 需关注点 (Orange) │ │ 针对性能力提升路线 (Blue)   │ │
│ │ • 总线通信工具契合│ │ • 边缘丢包场景稍弱│ │ 01. 强化车载以太网实操总结  │ │
│ │ • 回答逻辑层次分明│ │                   │ 02. 强化回答中的数据量化指标  │ │
│ └───────────────────┘ └───────────────────┘ └─────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 7. 异常状态与容错降级规范

| 异常场景 | 触发条件 | 前端 UI 表现 | 恢复动作 / 用户引导 |
| :--- | :--- | :--- | :--- |
| **加载中 (Loading)** | 接口响应返回前 | 全屏深色座舱骨架屏（Skeleton HUD），中央脉冲光波扩散，文案：“智驾面试仓正在解析考官双评证据与指标...” | 保持界面不抖动，禁用所有操作按钮 |
| **会话不存在 (404)** | `code === "SESSION_NOT_FOUND"` | 深红微光警示面板，HUD 图标：“会话记录不存在或已被重置 (#sid)” | 提供按钮：“返回首页重新开始” (`href="/"`) |
| **报告未生成 (404)** | `code === "REPORT_NOT_FOUND"` | 橙黄微光提示面板，HUD 图标：“报告尚未生成 (#sid)” | 提供操作按钮：手动“刷新报告”与“返回首页” (`href="/"`)，不执行自动轮询，不提供无法恢复原 sid 状态的虚假作答入口 |
| **网络异常 (5xx/断网)** | `fetch` 失败 / HTTP 500 / 503 | 红色边框告警卡：“座舱通信链路中断，请检查服务连通性” | 提供“重试加载”按钮 |
| **非法 sid (422)** | URL 参数非正整数（如 `/reports/abc`） | 友好提示：“无效的报告访问地址，参数格式不合规” | 提供“返回主页”按钮 |
| **整体分缺失** | `overall === null` | Overall 环形仪表中心显示 `--`，评级标注“待评估” | 正常渲染其他卡片，提示“当前有效评估不足” |
| **全部维度缺失** | 4 维分数全为 `null` | 隐藏雷达图，切换为线性降级槽（全显示“未评估”），四维卡片证据显示“未捕获”，Insights 显示“作答内容过短或未通过原话核验” | 页面不报错崩盘，允许正常查看判词与重新训练 |
| **证据串首尾空格** | 后端原样保留的带空格证据 | 前端渲染保持 `whitespace-pre`，并以醒目气泡标签框住 | 完整呈现原文字面证据，不自行扭曲 |

---

## 8. 未来实施精确文件边界

进入 T7-R1（报告页实现）时，**严格锁死文件边界**。必须使用已获批准的精准版本 `"echarts": "5.6.0"`（AGENTS.md §4、§10.1 已批准，MIT 协议，传递依赖由 lockfile 严格锁定），未经单独书面申请并获指挥官 Astra 批准，禁止修改任何额外文件：

### 默认允许修改与创建边界（共 6 个文件）：
1. `web/package.json`（声明精准版本 `"echarts": "5.6.0"` 生产依赖，并在 scripts 中配置确定性的 `"test": "node --experimental-strip-types --test web/tests/report.test.ts"` 脚本）
2. `web/package-lock.json`（安装依赖后由 npm 自动生成的确定性锁文件，锁定传递依赖）
3. `web/lib/report-data.ts`（报告页纯数据转换函数、雷达图指标计算与可空维度降级逻辑，供页面与测试共同导入，避免 Node 原生测试直接导入 TSX）
4. `web/app/reports/[sid]/page.tsx`（报告页核心组件、数据获取、ECharts 挂载与座舱 HMI 渲染逻辑，从 `web/lib/report-data.ts` 导入纯函数）
5. `web/app/globals.css`（仅限添加座舱微光动画、发光描边、深空背景等 CSS 工具类与 keyframes）
6. `web/tests/report.test.ts`（直接导入 `web/lib/report-data.ts` 进行纯函数单元测试，由 `npm test` 驱动）

### 扩界申请机制：
若在实施中发现需抽取独立组件（如 `web/components/ReportRadar.tsx`）或公共样式文件：
- 必须先在任务单中声明文件路径、代码职责与扩界理由；
- 获得指挥官 Astra 批准后方可建文件，禁止先行创建或跨界修改。

---

## 9. 验收矩阵（自动化与 30 秒人工验收）

### 9.1 测试机制分层与自动化用例设计 (T7-R1 前置)

由于前端轻量工程未引入 Jest / JSDOM / React Testing Library 等重型 DOM 模拟测试库（AGENTS.md 强调零不必要依赖与极简构建），本规格将测试与验收严格分层：
1. **纯数据转换与降级逻辑**：明确利用 Node 22.22+ 原生 TypeScript 类型剥离（Type Stripping）特性，由 `web/tests/report.test.ts` 直接导入纯逻辑模块 `web/lib/report-data.ts` 执行自动化单元测试，由 `web/package.json` 中的 `npm test` 脚本驱动；
2. **静态类型安全**：通过 `npm run typecheck`（`tsc --noEmit`）验证；
3. **真实后端数据契约回归**：通过 Python `pytest tests/test_text_flow.py tests/test_scoring.py` 验证真实落库 payload 与前端接口一致性；
4. **DOM 视觉排版与 ECharts Canvas 渲染**：由 §9.2 的 30 秒人工验收路径覆盖，不夸大宣称 DOM 自动化能力。

#### 自动化测试执行命令（统一确定命令，不设二选一）：
- **纯函数单元测试**：`npm test`（对应 `web/package.json` 中的执行定义严格为 `node --experimental-strip-types --test web/tests/report.test.ts`）
- **类型检查**：`npm run typecheck`（对应 `web/package.json` 中的执行定义严格为 `tsc --noEmit`）
- **后端契约集成**：`pytest tests/test_text_flow.py tests/test_scoring.py`

#### 单元测试用例清单 (`web/tests/report.test.ts`)
| 用例编号 | 测试目标 | 执行方式与断言要点 |
| :--- | :--- | :--- |
| **R-T01** | 正常 4 维有效数据转换 | 输入 4 个有效分数，调用 `transformDimensionsToRadar()`，断言 `canRenderRadar === true`，indicator 轴数严格为 4 |
| **R-T02** | 文本模式流畅度为 null 转换 | 输入 `expression_fluency.score = null`，断言 `canRenderRadar === true`，indicator 轴数严格为 3（剔除流畅度轴），values 不包含 0 |
| **R-T03** | 缺失 ≥2 维时的优雅降级 | 输入有效分数 < 3 个，断言 `canRenderRadar === false`，`radarOptions === null`，`validCount < 3` 触发线性降级标记 |
| **R-T04** | 全部维度为 null 极端数据 | 输入 4 维分数全为 null，断言 `canRenderRadar === false`，`validCount === 0`，不抛出异常 |
| **R-T05** | 证据原文字面值无损保留 | 验证带首尾空格、特殊标点与符号的原文字符串经数据传递原样保留，字面值完全一致 |

### 9.2 30 秒人工验收路径 (评审演练)
1. **0–5 秒（主视觉第一印象）**：
   - 浏览器打开实际会话报告（如 `http://localhost:3000/reports/1`）；
   - 核查全屏深色座舱氛围：背景暗黑底色、青蓝微光发光描边、无横向白边、无水平滚动条。
2. **5–15 秒（核心指标与雷达核验）**：
   - 查看 Overall 仪表盘大字（如 `85.7`）及环形进度；
   - 查看能力雷达图：清晰呈现 3 轴三角形（专业、逻辑、素养），流畅度未被画成 0 分，带有文本模式说明标签。
3. **15–22 秒（证据可解释性核验）**：
   - 检查专业匹配度卡片下的原话证据高亮气泡（如 `"使用CANoe分析报文"`）；
   - 确认引用短句字面完全等于作答原文，呈现考官判词。
4. **22–30 秒（行动清单与闭环入口）**：
   - 快速浏览改进建议项（如 SOME/IP 实操总结、STAR 量化）；
   - 确认底部“再次训练”按钮点击正常导航回 `/`；确认“查看成长记录”入口清晰醒目，点击导航至 `/growth`。

---

## 10. 契约审查与待批准事项总结

经对比当前后端实现代码与规格设计，得出以下结论：

### 10.1 当前后端支撑结论
- **结论**：当前后端的 `GET /api/reports/{sid}`（在 `server/api/reports.py` 实现）**完全足以支撑**上述报告页面的核心功能与全字段映射。现有字段已涵盖四维评分、原文字面证据、考官判词、亮点、顾虑、改进建议与 overall 综合分。
- **关于 T4 过渡语字段**：T4 阶段新增的 `SessionCreateResponse.transition_audio_urls` 与 `AnswerResponse.transition_audio_url` 已正式获批并合入 `main`（提交 `757a62f` / `fdd74a1`）。报告页自身不消费过渡语音频，因此无任何过渡语契约遗留问题。
- **关于成长追踪跳转**：遵循《成长追踪接口与身份规格（T7-G0）》（`docs/growth-tracking-spec.md`），报告页“查看成长记录”统一约定导航至 `/growth`（或可选携带 `/growth?job_id=${job_id}` 用于岗位筛选），由成长页承载学生档案的选择与呈现；**不得宣称跨页面自动继承同一 `user_id`**，学生身份在会话与成长页之间的连续传递与持久化机制交由下游任务 T7-G1 定稿。绝不引入未获支持的 `session_id` 查询参数。

### 10.2 待队长批准事项 (契约缺口备忘)
本规格书对后端 API 与数据库模型**无任何新增强制变更要求**。仅将以下非阻塞建议列为可选备忘：
1. **[待批准-可选] 报告接口补充会话元信息（受众模式与时间）**：
   - 当前 `ReportResponse` 仅包含 `id, session_id, job_title, overall, dimensions, highlights, concerns, improvement`。
   - 若报告页希望在 Header 中直接展示“评测时间（`started_at`）”与“受众模式（`mode`: 毕业生/新生）”，可由队长批准在后续 T7-G1 或 T8 中将此两字段补充至 `ReportResponse`。当前 M1 报告页不强依赖此信息，完全不阻塞 T7-R1 施工。
