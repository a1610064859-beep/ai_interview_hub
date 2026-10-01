const REQUIREMENTS = [
  { label: "加班意愿 / 作息", pattern: /加班意愿|(?:不想|不愿|拒绝|不接受|不能|不考虑|可接受|愿意|接受|可以|能接受)[^。；\n]{0,12}加班|双休|单休|周末休息|工作时间|作息|996|朝九晚五/ },
  { label: "加班费 / 补偿", pattern: /加班费|加班补偿|无偿加班|有偿加班|调休|加班.{0,8}(?:报酬|补偿|支付)/ },
  { label: "薪资期望", pattern: /(?:期望|期待|要求|最低|目标).{0,6}(?:薪资|薪酬|工资|月薪)|(?:薪资|薪酬).{0,6}(?:期望|要求)|薪资待遇|薪酬待遇/ },
  { label: "地点 / 工作方式", pattern: /(?:期望|意向).{0,6}(?:地点|城市)|工作地点|工作城市|就职地点|远程办公/ },
];
const REQUIREMENT_SECTION = /^(?:求职意向|求职要求|个人要求|工作偏好|期望待遇|就业意向)[：:]?$/;
const OTHER_SECTION = /^(?:教育|学习|实习|项目|工作|获奖|技能|自我评价|自我介绍|个人简介|专业技能|社会实践|培训)(?:经历|情况|背景|经验|介绍|证书)?[：:]?$/;

export function extractResumeRequirements(paragraphs: string[]) {
  const result = REQUIREMENTS.map(({ label }) => ({ label, quotes: [] as string[] }));
  const other = { label: "其他求职要求", quotes: [] as string[] };
  let inRequirements = false;
  let inExperience = false;
  const lines = paragraphs.flatMap((paragraph) => paragraph.split(/\r?\n/)).map((line) => line.trim()).filter(Boolean);
  for (let index = 0; index < lines.length; index += 1) {
    let line = lines[index];
    if (REQUIREMENT_SECTION.test(line)) { inRequirements = true; inExperience = false; continue; }
    if (OTHER_SECTION.test(line)) { inRequirements = false; inExperience = true; continue; }
    if (/^(?:工作|项目|实习|教育)经历[：:]/.test(line) || (inExperience && !/^(?:求职|期望|个人要求|加班意愿)/.test(line))) continue;
    if (/^[^：:]{2,12}[：:]$/.test(line) && REQUIREMENTS.some(({ pattern }) => pattern.test(line)) && lines[index + 1] && !OTHER_SECTION.test(lines[index + 1]) && !/^[^：:]{2,12}[：:]/.test(lines[index + 1])) {
      line += `\n${lines[++index]}`;
    }
    let matched = false;
    REQUIREMENTS.forEach(({ pattern }, groupIndex) => {
      if (pattern.test(line)) { if (!result[groupIndex].quotes.includes(line)) result[groupIndex].quotes.push(line); matched = true; }
    });
    if (!matched && (inRequirements || /^(?:求职要求|个人要求|工作偏好)[：:]/.test(line)) && !other.quotes.includes(line)) other.quotes.push(line);
  }
  return [...result, other];
}

export function extractResumeDetails(paragraphs: string[]) {
  const addressLabels = "现居住地|现居地址|现住址|家庭住址|居住地址|联系地址|通讯地址|现居地|居住地|现居|住址|地址";
  const schoolLabels = "毕业院校|毕业学校|就读院校|学校名称|学校名|院校名称|学校|院校";
  const detailLabels = `年龄|籍贯|祖籍|${addressLabels}|${schoolLabels}`;
  const bareLabel = new RegExp(`^(?:${detailLabels})[：:]?$`);
  const nextLabel = new RegExp(`\\s+(?:${detailLabels})\\s*[：:]`);
  const lines = paragraphs.flatMap((paragraph) => paragraph.split(/\r?\n/)).map((line) => line.trim()).filter(Boolean);
  const readable = lines.map((line, index) => {
    const next = lines[index + 1];
    if (bareLabel.test(line) && next && !bareLabel.test(next) && !OTHER_SECTION.test(next) && !/^[^：:]{2,12}[：:]/.test(next)) {
      return `${line.replace(/[：:]$/, "")}：${next}`;
    }
    return line;
  });
  const fields = [
    { label: "年龄", pattern: /(?:^|[\s，,；;])年龄\s*[：:]\s*([^\n，,；;]+)/ },
    { label: "籍贯", pattern: /(?:^|[\s，,；;|])(?:籍贯|祖籍)\s*[：:]\s*([^\n，,；;|\t]+)/ },
    { label: "现居 / 住址", pattern: new RegExp(`(?:^|[\\s，,；;|])(?:${addressLabels})\\s*[：:]\\s*([^\\n，,；;|\\t]+)`) },
    { label: "毕业院校", pattern: new RegExp(`(?:^|[\\s，,；;|])(?:${schoolLabels})\\s*[：:]\\s*([^\\n，,；;|\\t]+)`) },
  ];
  return fields.flatMap(({ label, pattern }) => {
    for (const paragraph of readable) {
      const match = paragraph.match(pattern);
      if (match) {
        const value = match[1].split(nextLabel)[0].trim();
        if (value) return [{ label, value }];
      }
    }
    return [];
  });
}
