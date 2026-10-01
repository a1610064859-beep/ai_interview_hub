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

test("住址支持常见简历标签，并分开读取同一行的籍贯与住址", () => {
  for (const label of ["住址", "现住址", "家庭住址", "现居住地", "居住地址", "联系地址", "通讯地址", "地址"]) {
    assert.deepEqual(extractResumeDetails([`${label}：上海市浦东新区`]), [{ label: "现居 / 住址", value: "上海市浦东新区" }]);
  }
  assert.deepEqual(extractResumeDetails(["籍贯：江苏省南京市 现住址：上海市浦东新区"]), [
    { label: "籍贯", value: "江苏省南京市" }, { label: "现居 / 住址", value: "上海市浦东新区" },
  ]);
});

test("籍贯和住址支持表格中分开的标签与值，不把项目地点当成住址", () => {
  assert.deepEqual(extractResumeDetails(["籍贯：", "江苏省南京市", "住址", "上海市浦东新区"]), [
    { label: "籍贯", value: "江苏省南京市" }, { label: "现居 / 住址", value: "上海市浦东新区" },
  ]);
  assert.deepEqual(extractResumeDetails(["项目地点：上海", "户籍所在地：江苏", "籍贯：", "教育经历"]), []);
});

test("学校名称读取实际院校名，不把学校档次当成学校名称", () => {
  for (const label of ["学校名", "学校名称", "学校", "院校", "院校名称", "毕业院校", "毕业学校", "就读院校"]) {
    assert.deepEqual(extractResumeDetails([`${label}：上海某职业院校`]), [{ label: "毕业院校", value: "上海某职业院校" }]);
  }
  assert.deepEqual(extractResumeDetails(["学校档次：211/双一流"]), []);
});
