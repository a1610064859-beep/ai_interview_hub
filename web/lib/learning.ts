export type StarPart = "situation" | "task" | "action" | "result";
export type StarDraft = Record<StarPart, string>;
export type LearningTopic = "hear" | "star" | "intro" | "followup" | "unknown" | "review";

export const starParts: { key: StarPart; letter: string; english: string; title: string; prompt: string; example: string }[] = [
  { key: "situation", letter: "S", english: "Situation", title: "情境", prompt: "这件事发生在什么场景？你当时是什么角色？", example: "课程展示前，组员提交的资料版本不一致。" },
  { key: "task", letter: "T", english: "Task", title: "任务", prompt: "要解决什么问题，或者要完成什么目标？", example: "我负责在截止前整理并核对最终版。" },
  { key: "action", letter: "A", english: "Action", title: "行动", prompt: "你本人具体做了哪几步？团队工作请分清自己的贡献。", example: "我建立清单，逐一确认文件来源和负责人，统一命名后复核。" },
  { key: "result", letter: "R", english: "Result", title: "结果", prompt: "实际发生了什么？如果没有成果数字，可以说反馈和复盘。", example: "小组按时完成展示；复盘后决定提前约定资料格式。" },
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

export const interviewKnowledge = [
  {
    id: "prepare", title: "面试前：准备岗位与自己的材料", summary: "把岗位要求和真实经历对上号。",
    mistake: "只背一份通用答案，面试时才发现问题围绕另一项职责。",
    method: ["读岗位描述，圈出工作任务、工具和能力要求。", "各找一段能说明能力的真实经历；没有相关经历就准备相近课程练习。", "把项目的角色、做法、结果写在一张纸上，练习用自己的话讲。"],
    example: "看到岗位要求“记录并复现缺陷”，可以准备一次课程项目里你如何保留输入、定位问题的真实经历。",
    practice: "从目标岗位挑两个要求，每项写下自己能举的事实和还要补的知识。",
  },
  {
    id: "technical", title: "知识题与情景题：先给判断，再说依据", summary: "先回答问题，再解释条件、方法和取舍。",
    mistake: "被问两种方法的差别，却直接讲一大段个人经历；遇到情景题只说“我会认真处理”。",
    method: ["知识比较题：先说区别，再说各自适用条件和一个例子。", "情景处理题：先确认目标与约束，再讲处理顺序、验证方式和风险。", "不确定的地方明确说出边界，不把猜测包装成结论。"],
    example: "问“发现偶发故障怎么办”，可先说保留版本和输入，再尝试复现，最后记录未排除的风险与后续验证。",
    practice: "用三句话回答一道比较题：主要区别、各自场景、仍需确认的条件。",
  },
  {
    id: "questions", title: "轮到你提问：了解工作，也展示准备", summary: "围绕岗位任务与学习机会提出具体问题。",
    mistake: "只说“没有问题”，或提出岗位描述中已经写明、自己还没读过的问题。",
    method: ["问新人会参与哪些具体任务，能了解真实工作内容。", "问团队如何判断任务完成得好，能了解评价标准。", "问入职初期最需要补的能力，能规划学习重点。"],
    example: "“如果我加入测试团队，最开始会接触哪类测试任务？团队怎样确认一次问题复现已经足够可靠？”",
    practice: "针对目标岗位写两句反问：一句问工作任务，一句问能力与反馈。",
  },
  {
    id: "remote", title: "线上面试：设备、环境与沟通节奏", summary: "让面试官听得清，也让自己有时间思考。",
    mistake: "开始前不检查麦克风；听不清时硬猜；网络卡顿后接着讲，却不知道对方是否听到。",
    method: ["提前测试麦克风、耳机、摄像头和连接，选择安静、明亮的环境。", "回答前短暂停顿整理重点；说完一部分可确认对方是否听清。", "遇到声音中断，礼貌说明并请求重复关键问题或重述自己的最后一句。"],
    example: "“刚才声音有些中断，我听到的是‘如何处理偶发问题’，请问您还问到了验证方法吗？”",
    practice: "做一次三十秒录音回放：检查音量、杂音，并练习一句澄清话术。",
  },
] as const;
