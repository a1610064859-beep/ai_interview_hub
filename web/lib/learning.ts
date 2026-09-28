export type StarPart = "situation" | "task" | "action" | "result";
export type StarDraft = Record<StarPart, string>;
export type LearningTopic = "hear" | "star" | "intro" | "followup" | "unknown" | "review";

export const starParts: { key: StarPart; letter: string; title: string; prompt: string }[] = [
  { key: "situation", letter: "S", title: "情境", prompt: "这件事发生在什么场景？你当时是什么角色？" },
  { key: "task", letter: "T", title: "任务", prompt: "要解决什么问题，或者要完成什么目标？" },
  { key: "action", letter: "A", title: "行动", prompt: "你本人具体做了哪几步？团队工作请分清自己的贡献。" },
  { key: "result", letter: "R", title: "结果", prompt: "实际发生了什么？如果没有成果数字，可以说反馈和复盘。" },
];

export function reviewStarDraft(draft: StarDraft): StarPart[] {
  return starParts.map((part) => part.key).filter((key) => !draft[key].trim());
}

export function buildStarDraft(draft: StarDraft): string {
  return starParts.map((part) => draft[part.key].trim()).filter(Boolean).join("\n");
}

export const questionExercises = [
  {
    id: "project", kind: "experience" as const,
    question: "请讲一次课程项目遇到困难，你是怎样处理的？",
    options: [
      { label: "说明困难、本人采取的行动，以及实际结果", correct: true, explanation: "题目要听一段具体经历。先交代问题，再重点讲自己的做法和结果；可以用 STAR 组织。" },
      { label: "介绍课程学过的所有知识点", correct: false, explanation: "只罗列知识点，没有回应“遇到什么困难、怎样处理”，面试官仍听不出你的行动。" },
      { label: "只说团队很努力，最后顺利完成", correct: false, explanation: "这句话缺少困难细节和个人贡献。请说清你负责的步骤与真实结果。" },
    ],
  },
  {
    id: "knowledge", kind: "knowledge" as const,
    question: "请比较台架测试与实地测试各自适合解决什么问题。",
    options: [
      { label: "先给比较结论，再说两者各自的适用场景", correct: true, explanation: "这是比较题。先分清两种测试各自能验证什么，再举例；无需硬套一段个人经历。" },
      { label: "先讲一段自己参加社团的完整 STAR 故事", correct: false, explanation: "这道题问的是概念与适用场景。STAR 用于经历类题，这里先直接比较两者。" },
      { label: "只回答两者都很重要", correct: false, explanation: "两者都重要并没有回答区别。至少说明各自侧重和一个典型场景。" },
    ],
  },
];

export const learningLessons: {
  id: LearningTopic; title: string; summary: string; mistake: string; method: string[]; example: string; practice: string;
}[] = [
  { id: "hear", title: "先听懂面试官在问什么", summary: "找动作词、对象和范围，再开口。", mistake: "听见熟悉词就讲经历，却漏了“为什么”“如何比较”等关键要求。", method: ["抓动作词：介绍、比较、说明原因、举例。", "把两部分问题分开回答；必要时先用一句话确认。", "先给直接回答，再补一条依据或例子。"], example: "问“遇到什么困难、怎样处理”时，先交代困难，再说自己的处理步骤。", practice: "找一道题，写下“要做什么、围绕什么、答几部分”。" },
  { id: "star", title: "STAR：把真实经历讲清楚", summary: "经历题讲情境、任务、行动、结果。", mistake: "每题都套 STAR，铺垫过长，或把团队工作全说成自己做的。", method: ["S 情境和 T 任务尽量简短。", "A 行动是重点：讲清楚自己做了什么。", "R 结果只写真实发生的事；没有数字也能说明反馈与复盘。"], example: "课程展示前资料格式不一；我负责汇总，建立清单核对分工；按时交稿后发现需要更早约定格式。", practice: "选一段真实经历，分别写四句。" },
  { id: "intro", title: "一分钟自我介绍", summary: "专业、相关经历、目标，给面试官留下可追问的线索。", mistake: "从头背简历，只说“认真负责”，没有具体例子。", method: ["说清自己在学什么。", "挑一件与岗位相关、确实做过的事。", "说明这次训练想了解或争取什么。"], example: "“我学习车辆工程，课程项目中负责整理雨天视频并统计漏检情况。我希望了解测试岗位如何验证边界场景。”", practice: "录一段约一分钟的介绍，检查听者能否复述你的专业、例子与目标。" },
  { id: "followup", title: "接住追问与请求澄清", summary: "先直接回答，再补具体事实。", mistake: "把追问当否定，一遍遍重复原答案；没听清时猜着答。", method: ["不确定题意时，礼貌确认关键条件。", "追问本人贡献时，区分自己和团队做的事。", "一句话答核心，再补一个可以核实的细节。"], example: "“您想了解的是我负责的部分，对吗？我主要核对数据来源，并整理成可复查的清单。”", practice: "请同伴连续追问一段经历两次，每次先用一句话答重点。" },
  { id: "unknown", title: "不会的问题也能诚实回答", summary: "说明边界、相关基础和补学方法。", mistake: "不懂也硬答，编造项目、操作记录或无法核对的数字。", method: ["明确目前没实际接触过什么。", "说出真正相关的课程或相近练习。", "说明会如何查规范、验证和求助。"], example: "“这个工具我还没实际用过。我做过相近的数据整理，会先看操作规范，再用练习数据熟悉流程。”", practice: "找一个陌生术语，用三句话说“不熟的部分、已有基础、下一步”。" },
  { id: "review", title: "读懂反馈，再练一次", summary: "核对原话和分析，挑一个具体动作改进。", mistake: "只盯总分，把一次模型评分当成对能力的最终结论。", method: ["先核对引用是否真出自你的回答。", "再看分析是否对应这段话；有疑问时不要盲从。", "选一条可操作的建议，重答同类题并回看变化。"], example: "若回答只说“我们完成了项目”，可补自己负责的步骤、材料和真实结果。", practice: "从报告选一条建议，指出支撑它的回答原话，再重答一次。" },
];
