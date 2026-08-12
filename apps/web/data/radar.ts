export type EvidenceGrade = "A" | "B" | "C" | "D" | "E";
export type EvidenceState = "已验证" | "待交叉验证" | "监测中" | "已更正";
export type EventKind = "模型" | "产品" | "研究" | "基础设施" | "政策" | "安全";

export interface Source {
  id?: string;
  name: string;
  href: string;
  kind: "第一方" | "独立报道" | "论文" | "监管文件";
}

export interface EventClaim {
  id: string;
  text: string;
  status: "成立" | "厂商自报" | "待验证" | "被反驳";
  evidenceLabel: string;
  evidenceHref?: string;
}

export interface RadarEvent {
  apiId?: string;
  slug: string;
  title: string;
  kicker: string;
  summary: string;
  delta: string;
  score: number;
  confidence: EvidenceGrade;
  evidence: EvidenceState;
  kind: EventKind;
  time: string;
  timeAgo: string;
  action: string;
  actionSlug: string;
  waveform: number[];
  sources: Source[];
  unknowns: string[];
  affected: string[];
  claims?: EventClaim[];
}

export interface ActionRecipe {
  slug: string;
  title: string;
  duration: string;
  difficulty: "5 分钟" | "30 分钟" | "半天";
  outcome: string;
  risk: string;
  relatedEvent: string;
  steps: string[];
}

export interface Story {
  slug: string;
  title: string;
  status: string;
  summary: string;
  movement: string;
  events: string[];
}

export interface Briefing {
  date: string;
  title: string;
  count: number;
  note: string;
  summary?: string;
  cutoffAt?: string;
  generatedAt?: string;
  eventSlugs?: string[];
}

const source = (name: string, href: string, kind: Source["kind"]): Source => ({ name, href, kind });

/** A local, typed adapter. Replacing this module with API fetches leaves page contracts intact. */
export const radarEvents: RadarEvent[] = [
  {
    slug: "open-weight-reasoner-release",
    title: "开放权重推理模型把 32B 档位推到可部署边界",
    kicker: "模型 / 真实可用性",
    summary: "新权重与推理配方公开；官方给出工具调用与长上下文结果，但第三方复现仍在积累。",
    delta: "新增可下载权重与推理配置",
    score: 91,
    confidence: "A",
    evidence: "已验证",
    kind: "模型",
    time: "08:12",
    timeAgo: "18 分钟前",
    action: "用你的 20 个真实任务做一次成本/质量对照",
    actionSlug: "benchmark-open-reasoner",
    waveform: [11, 14, 13, 20, 16, 27, 38, 33, 71, 91, 58, 42, 29, 34, 22, 20, 18, 23],
    sources: [
      source("模型卡与权重仓库", "https://huggingface.co/", "第一方"),
      source("技术报告", "https://arxiv.org/", "论文")
    ],
    unknowns: ["生产吞吐与并发尚无独立基准", "特定语言和工具场景的退化范围待验证"],
    affected: ["开发", "研究", "自托管团队"]
  },
  {
    slug: "agent-api-audit-log",
    title: "Agent API 新增可回放审计日志",
    kicker: "产品 / 可控性",
    summary: "调用链、工具参数与中断原因可按运行回放，企业隔离与保留策略同步更新。",
    delta: "审计轨迹从测试能力进入正式 API",
    score: 78,
    confidence: "A",
    evidence: "已验证",
    kind: "产品",
    time: "07:46",
    timeAgo: "44 分钟前",
    action: "为一个高价值工作流启用日志并定义人工复核点",
    actionSlug: "audit-an-agent",
    waveform: [9, 10, 12, 15, 18, 21, 20, 29, 46, 42, 36, 55, 78, 51, 31, 23, 18, 14],
    sources: [source("开发者更新日志", "https://platform.openai.com/docs", "第一方")],
    unknowns: ["不同地区的数据留存默认值需在控制台确认"],
    affected: ["产品", "合规", "运营"]
  },
  {
    slug: "gpu-supply-guidance",
    title: "云端 GPU 供给指引更新，短租价格出现分化",
    kicker: "基础设施 / 成本",
    summary: "主流云区间的现货与预留价格差继续扩大，低延迟区域的可用性仍然紧张。",
    delta: "新增区域级容量与价格说明",
    score: 67,
    confidence: "B",
    evidence: "待交叉验证",
    kind: "基础设施",
    time: "06:55",
    timeAgo: "95 分钟前",
    action: "核对下一个训练周期的区域、可抢占策略和退出价格",
    actionSlug: "check-gpu-exposure",
    waveform: [10, 17, 22, 17, 20, 30, 29, 32, 27, 36, 45, 39, 51, 67, 44, 31, 17, 11],
    sources: [source("云服务公告", "https://cloud.google.com/blog", "第一方"), source("产业追踪", "https://www.reuters.com/technology/", "独立报道")],
    unknowns: ["合约折扣与实际排队时间不可从公开价格推断"],
    affected: ["基础设施", "采购", "创业团队"]
  },
  {
    slug: "copyright-training-case",
    title: "训练数据版权案进入证据披露窗口",
    kicker: "政策 / 期限",
    summary: "法院时间表确认关键材料将进入披露；结果并不等于最终裁决，但会影响风险评估节奏。",
    delta: "程序性日期确定，实质裁决尚未发生",
    score: 61,
    confidence: "A",
    evidence: "监测中",
    kind: "政策",
    time: "05:30",
    timeAgo: "3 小时前",
    action: "把使用来源和资产权利状态纳入下次供应商复审",
    actionSlug: "map-copyright-risk",
    waveform: [8, 11, 9, 18, 22, 17, 23, 31, 24, 27, 39, 33, 41, 61, 50, 31, 22, 14],
    sources: [source("法院案卷", "https://www.courtlistener.com/", "监管文件")],
    unknowns: ["披露材料是否支持关键主张仍不可知"],
    affected: ["法务", "内容", "采购"]
  },
  {
    slug: "vision-benchmark-correction",
    title: "视觉基准榜单修正了一组重复样本",
    kicker: "研究 / 更正",
    summary: "维护方确认部分测试样本存在重合，已发布修订分数与受影响模型列表。",
    delta: "两个排名结论被下调，原始结果保留可追溯版本",
    score: 54,
    confidence: "A",
    evidence: "已更正",
    kind: "研究",
    time: "04:18",
    timeAgo: "4 小时前",
    action: "不要用单一榜单决定图像模型迁移",
    actionSlug: "triangulate-vision-models",
    waveform: [5, 7, 12, 10, 15, 23, 19, 31, 28, 42, 54, 48, 37, 25, 18, 16, 11, 9],
    sources: [source("基准修订说明", "https://github.com/", "第一方")],
    unknowns: ["下游采用方是否已更新内部选择标准"],
    affected: ["研究", "设计", "产品"]
  }
];

export const actions: ActionRecipe[] = [
  {
    slug: "benchmark-open-reasoner",
    title: "做一次开放推理模型对照",
    duration: "30 分钟",
    difficulty: "30 分钟",
    outcome: "得到可迁移 / 不可迁移的任务边界，而非泛化印象。",
    risk: "不要把厂商基准替代你自己的真实任务。",
    relatedEvent: "open-weight-reasoner-release",
    steps: ["挑选 20 个已知答案或可人工判定的真实任务。", "固定提示、工具与预算，分别运行现有方案和候选模型。", "记录成功率、耗时、异常类型与人工返工时间。", "只迁移连续两轮都稳定的任务；其余保持观察。"]
  },
  {
    slug: "audit-an-agent",
    title: "为一个 Agent 工作流加上审计点",
    duration: "5 分钟",
    difficulty: "5 分钟",
    outcome: "明确何时可自动执行、何时必须由人确认。",
    risk: "日志中可能含有业务或个人数据，先确认保留策略。",
    relatedEvent: "agent-api-audit-log",
    steps: ["选择影响最可控的一个工作流。", "打开运行回放，标记不可逆操作之前的工具调用。", "为该位置添加人工确认或停止条件。", "一周后复盘失败模式，再决定是否扩大范围。"]
  },
  {
    slug: "check-gpu-exposure",
    title: "检查本季度 GPU 暴露度",
    duration: "半天",
    difficulty: "半天",
    outcome: "形成区域、价格上限和替代容量的可执行清单。",
    risk: "公开价格不含你的私有合约与排队成本。",
    relatedEvent: "gpu-supply-guidance",
    steps: ["导出未来 90 天的训练和推理需求。", "按区域、实例和可抢占属性拆分成本。", "为关键任务定义第二可用区域和退出阈值。", "将异常价格和排队时长纳入周度观察。"]
  },
  {
    slug: "map-copyright-risk",
    title: "梳理生成内容的权利状态",
    duration: "30 分钟",
    difficulty: "30 分钟",
    outcome: "知道哪些资产需要进一步法务确认。",
    risk: "这不是法律意见；高风险用途请咨询专业人士。",
    relatedEvent: "copyright-training-case",
    steps: ["列出当前生产工作流使用的模型和素材来源。", "标记客户素材、公开素材和未知来源素材。", "保存产品条款与版本日期的快照。", "把不确定资产送入人工复核队列。"]
  },
  {
    slug: "triangulate-vision-models",
    title: "用三组真实素材复核视觉模型",
    duration: "30 分钟",
    difficulty: "30 分钟",
    outcome: "得到比单一偏好榜更接近生产约束的模型选择记录。",
    risk: "测试素材必须确认权利状态，不上传客户机密或未授权人物图像。",
    relatedEvent: "vision-benchmark-correction",
    steps: ["准备人物、文字与品牌一致性三组已授权素材。", "固定提示和随机种子，对候选模型各生成一组结果。", "分别记录构图、文字、可控性与返工时间。", "保留失败样本，并在榜单再次修订后复测。"]
  }
];

export const stories: Story[] = [
  { slug: "reasoning-goes-local", title: "推理能力正在下沉到可控部署", status: "加速中", summary: "能力、成本与运维约束在同一个迁移窗口内碰撞。", movement: "过去 14 天新增 6 个可运行证据", events: ["open-weight-reasoner-release", "agent-api-audit-log"] },
  { slug: "agent-governance", title: "Agent 从演示走向可审计运行", status: "持续验证", summary: "权限、回放和责任边界比自主性宣传更决定采用。", movement: "过去 7 天新增 3 个产品与政策信号", events: ["agent-api-audit-log", "copyright-training-case"] },
  { slug: "benchmark-reality", title: "模型评测正在被复现压力重塑", status: "出现修正", summary: "单项领先越来越难以替代真实场景验证。", movement: "今天新增 1 条公开更正", events: ["vision-benchmark-correction"] }
];

export const findEvent = (slug: string): RadarEvent | undefined => radarEvents.find((event) => event.slug === slug);
export const findAction = (slug: string): ActionRecipe | undefined => actions.find((action) => action.slug === slug);
export const findStory = (slug: string): Story | undefined => stories.find((story) => story.slug === slug);

export const claimsForEvent = (event: RadarEvent): EventClaim[] => {
  if (event.claims) return event.claims;
  const primarySource = event.sources[0];
  const independentSource = event.sources.find((item) => item.kind !== "第一方");
  return [
    {
      id: `claim-${event.slug}-delta`,
      text: event.delta,
      status: event.confidence === "A" ? "成立" : "待验证",
      evidenceLabel: primarySource?.name ?? "原始来源",
      evidenceHref: primarySource?.href ?? "#sources"
    },
    {
      id: `claim-${event.slug}-scope`,
      text: event.summary,
      status: independentSource ? "成立" : "厂商自报",
      evidenceLabel: independentSource?.name ?? primarySource?.name ?? "来源待补",
      evidenceHref: independentSource?.href ?? primarySource?.href ?? "#sources"
    },
    {
      id: `claim-${event.slug}-unknown`,
      text: event.unknowns[0] ?? "仍需等待真实采用与独立复现。",
      status: "待验证",
      evidenceLabel: "下一验证条件",
      evidenceHref: "#next-check"
    }
  ];
};

export const briefings: Briefing[] = [
  { date: "2026-08-12", title: "早间快照", count: 18, note: "事件簇 12 · 新增可验证证据 7" },
  { date: "2026-08-11", title: "日终快照", count: 26, note: "事件簇 17 · 公开更正 1" }
];
