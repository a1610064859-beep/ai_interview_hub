import assert from "node:assert/strict";
import test from "node:test";
import { extractResumeDetails, extractResumeRequirements } from "../lib/resume-data.ts";

test("求职要求保留原话，分开展示加班意愿和加班费", () => {
  const rows = extractResumeRequirements(["个人要求：不想加班，希望双休。", "加班费：按规定支付或安排调休。", "期望薪资：税前 8000 元。"]);
  assert.deepEqual(rows.find((row) => row.label === "加班意愿 / 作息")?.quotes, ["个人要求：不想加班，希望双休。"]);
  assert.deepEqual(rows.find((row) => row.label === "加班费 / 补偿")?.quotes, ["加班费：按规定支付或安排调休。"]);
  assert.deepEqual(rows.find((row) => row.label === "薪资期望")?.quotes, ["期望薪资：税前 8000 元。"]);
});

test("单独一行的要求标题绑定下一行，经历中的加班不当作求职意愿", () => {
  const rows = extractResumeRequirements(["项目经历：加班完成测试报告。", "加班意愿：", "不接受无偿加班", "期望薪资：", "8000–10000 元", "教育经历", "车辆工程"]);
  assert.deepEqual(rows.find((row) => row.label === "加班意愿 / 作息")?.quotes, ["加班意愿：\n不接受无偿加班"]);
  assert.deepEqual(rows.find((row) => row.label === "薪资期望")?.quotes, ["期望薪资：\n8000–10000 元"]);
  assert.equal(rows.some((row) => row.quotes.some((quote) => quote.includes("项目经历"))), false);
});

test("简历未注明的信息不推断，个人资料仅取有标签的原文", () => {
  assert.equal(extractResumeRequirements(["工作经历：周末参与加班排查，记录补偿方案。"]).every((row) => row.quotes.length === 0), true);
  assert.deepEqual(extractResumeDetails(["年龄：22岁", "籍贯：上海", "毕业院校：上海某职业院校", "项目经历：车辆测试"]), [
    { label: "年龄", value: "22岁" }, { label: "籍贯", value: "上海" }, { label: "毕业院校", value: "上海某职业院校" },
  ]);
});
