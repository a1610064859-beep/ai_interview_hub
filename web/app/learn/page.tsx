"use client";

import Link from "next/link";
import { useState } from "react";
import {
  buildStarDraft,
  interviewKnowledge,
  learningLessons,
  questionExercises,
  reviewStarDraft,
  starParts,
  type StarDraft,
  type StarPart,
} from "../../lib/learning";
import styles from "./page.module.css";

const emptyDraft: StarDraft = { situation: "", task: "", action: "", result: "" };
const allLessons = [...learningLessons, ...interviewKnowledge];

const diagnose = {
  question: "面试官问：请讲一次你在小组项目中解决困难的经历。",
  answer: "我们遇到很多问题，大家都很努力，最后顺利完成了。",
  choices: [
    { label: "这段话太短，所以一定要编更多细节", correct: false, why: "长度并非关键。需要补真实且能核对的情境与行动，不能编造。" },
    { label: "听不出“我”负责什么、具体怎样处理", correct: true, why: "对。问题问的是你如何处理困难，应讲明你的职责、做法和真实结果。" },
    { label: "只要补一个很大的结果数字就够了", correct: false, why: "不能编数字。先把真实的个人行动说清楚；结果也可以是反馈或学到的做法。" },
  ],
};

const buildChoices: Record<StarPart, { good: string; weak: string; why: string }> = {
  situation: { good: "课程展示前，我们小组的材料格式不一致。", weak: "我一直认为团队合作很重要。", why: "情境应交代发生了什么，空泛观点无法让听者进入这段经历。" },
  task: { good: "我负责把材料汇总成能按时提交的版本。", weak: "当时事情有很多，很复杂。", why: "任务要说清你的责任或需要解决的问题。" },
  action: { good: "我列出缺失项，逐一核对来源，并请组员确认各自负责的部分。", weak: "我们很努力，做了很多事情。", why: "行动应具体说明自己做了什么；团队分工也可以提，但别替别人认领成果。" },
  result: { good: "材料按时提交，我也意识到应该更早统一格式。", weak: "结果特别成功，大家都很满意。", why: "结果写实际发生的事；没有排名或数字时，说明真实反馈与复盘即可。" },
};

export default function LearnPage() {
  const [answers, setAnswers] = useState<Record<string, number>>({});
  const [diagnosis, setDiagnosis] = useState<number | null>(null);
  const [choices, setChoices] = useState<Partial<Record<StarPart, "good" | "weak">>>({});
  const [draft, setDraft] = useState<StarDraft>(emptyDraft);
  const [reviewed, setReviewed] = useState(false);
  const missing = reviewStarDraft(draft);
  const built = buildStarDraft(draft);
  const assembled = starParts.map(({ key }) => choices[key] ? buildChoices[key][choices[key]] : "").filter(Boolean).join("\n");

  return (
    <main className={styles.shell}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>面试仓 · 学习菜单</p>
          <h1>先学会表达，再开始面试</h1>
          <p className={styles.lead}>从听懂问题，到讲清一次真实经历。练习内容只保留在当前页面，不影响正式报告分数。</p>
        </div>
        <div className={styles.headerActions}>
          <Link href="/counsel">新生岗位路径</Link>
          <Link href="/">返回面试仓</Link>
        </div>
      </header>

      <p className={styles.menuHeading}>回答基础</p>
      <nav aria-label="回答基础学习菜单" className={styles.menu}>
        {learningLessons.map((lesson, i) => <a key={lesson.id} href={`#${lesson.id}`}><span>{String(i + 1).padStart(2, "0")}</span>{lesson.title}</a>)}
      </nav>
      <p className={styles.menuHeading}>更多面试知识</p>
      <nav aria-label="更多面试知识菜单" className={styles.menu}>
        {interviewKnowledge.map((lesson, i) => <a key={lesson.id} href={`#${lesson.id}`}><span>{String(i + 7).padStart(2, "0")}</span>{lesson.title}</a>)}
      </nav>

      <section className={styles.intro}>
        <p className={styles.kicker}>先记住两件事</p>
        <div className={styles.introGrid}>
          <div><strong>看问题类型</strong><p>经历题讲具体做法，可用 STAR；知识题和比较题先直接回答，再解释理由。</p></div>
          <div><strong>说真实经历</strong><p>课程、社团、志愿和练习都能用。讲自己做的事；没有数据时不必编造数字。</p></div>
        </div>
      </section>

      <div className={styles.lessonList}>
        {allLessons.map((lesson, i) => <section id={lesson.id} key={lesson.id} className={styles.lesson} aria-labelledby={`${lesson.id}-title`}>
          <div className={styles.lessonHeading}><span className={styles.number}>{String(i + 1).padStart(2, "0")}</span><div><h2 id={`${lesson.id}-title`}>{lesson.title}</h2><p>{lesson.summary}</p></div></div>
          {lesson.id === "star" && <div className={styles.starExplainer}>
            <p><strong>STAR 是什么？</strong>它是回答“请讲一次你如何处理问题”这类经历题的四步叙述方法。四个字母分别是 Situation（情境）、Task（任务）、Action（行动）、Result（结果）。按这个顺序说，面试官能听清发生了什么、你做了什么、最后怎样。</p>
            <p className={styles.starQuestion}>例题：请讲一次你和同学协作完成任务的经历。</p>
            <div className={styles.starGrid}>{starParts.map((part) => <div key={part.key} className={styles.starCard}>
              <span className={styles.starLetter}>{part.letter}</span>
              <strong>{part.english} · {part.title}</strong>
              <p>{part.prompt}</p>
              <p className={styles.starExample}>{part.example}</p>
            </div>)}</div>
            <p className={styles.starNote}>记住：情境和任务简短交代，行动重点讲<strong>你本人具体做了什么</strong>，结果只讲真实发生的事。知识题、比较题先直接回答，不必套用 STAR。</p>
          </div>}
          <div className={styles.lessonColumns}>
            <div><h3>容易答偏的地方</h3><p>{lesson.mistake}</p><h3>你可以这样说</h3><p>{lesson.example}</p></div>
            <div><h3>做法</h3><ol>{lesson.method.map((m) => <li key={m}>{m}</li>)}</ol><div className={styles.practiceTip}><strong>30 秒小练习</strong><p>{lesson.practice}</p></div></div>
          </div>
        </section>)}
      </div>

      <section className={styles.workshop} aria-labelledby="workshop-title">
        <p className={styles.eyebrow}>互动工坊 · 参考四步递进练习</p>
        <h2 id="workshop-title">识别 → 诊断 → 搭建 → 写自己的答案</h2>
        <p className={styles.lead}>练习会立即解释选择理由。这里的检查只帮助整理答案，不代表面试评分。</p>

        <div className={styles.workshopStep}>
          <div className={styles.stepTitle}><span>01</span><h3>识别：面试官真正想听什么？</h3></div>
          {questionExercises.map((q) => <fieldset key={q.id} className={styles.exercise}>
            <legend>{q.question}</legend>
            {q.options.map((option, idx) => <label key={option.label} className={styles.choice}>
              <input type="radio" name={q.id} checked={answers[q.id] === idx} onChange={() => setAnswers((prev) => ({ ...prev, [q.id]: idx }))} />
              <span>{option.label}</span>
            </label>)}
            {answers[q.id] !== undefined && <p className={styles.explanation} role="status"><strong>{q.options[answers[q.id]].correct ? "答对了：" : "再想想："}</strong>{q.options[answers[q.id]].explanation}</p>}
          </fieldset>)}
        </div>

        <div className={styles.workshopStep}>
          <div className={styles.stepTitle}><span>02</span><h3>诊断：这段回答最大的问题是什么？</h3></div>
          <p className={styles.question}>{diagnose.question}</p><blockquote>{diagnose.answer}</blockquote>
          <fieldset className={styles.exercise}><legend>选出最需要先改的地方</legend>
            {diagnose.choices.map((choice, idx) => <label key={choice.label} className={styles.choice}>
              <input type="radio" name="diagnose" checked={diagnosis === idx} onChange={() => setDiagnosis(idx)} /><span>{choice.label}</span>
            </label>)}
            {diagnosis !== null && <p className={styles.explanation} role="status"><strong>{diagnose.choices[diagnosis].correct ? "抓到重点了：" : "看看这点："}</strong>{diagnose.choices[diagnosis].why}</p>}
          </fieldset>
        </div>

        <div className={styles.workshopStep}>
          <div className={styles.stepTitle}><span>03</span><h3>搭建：为每段挑一句能回答问题的话</h3></div>
          <p className={styles.question}>题目：请讲一次你和同学协作完成任务的经历。</p>
          {starParts.map((part) => <fieldset key={part.key} className={styles.exercise}><legend>{part.letter} · {part.title}：{part.prompt}</legend>
            {(["good", "weak"] as const).map((kind) => <label key={kind} className={styles.choice}>
              <input type="radio" name={`build-${part.key}`} checked={choices[part.key] === kind} onChange={() => setChoices((prev) => ({ ...prev, [part.key]: kind }))} />
              <span>{buildChoices[part.key][kind]}</span>
            </label>)}
            {choices[part.key] && <p className={styles.explanation} role="status">{buildChoices[part.key].why}</p>}
          </fieldset>)}
          {assembled && <div className={styles.preview}><h4>面试官听到的连贯回答</h4><p>{assembled}</p></div>}
        </div>

        <div className={styles.workshopStep}>
          <div className={styles.stepTitle}><span>04</span><h3>轮到你：用一段真实经历试着写</h3></div>
          <p className={styles.question}>可以选择课程作业、社团、志愿或实习。只写确实发生过的事，尽量突出本人行动。</p>
          <div className={styles.draftGrid}>{starParts.map((part) => <label key={part.key} className={styles.draftField}>
            <span><strong>{part.letter} · {part.title}</strong>　{part.prompt}</span>
            <textarea value={draft[part.key]} rows={4} onChange={(event) => { setDraft((prev) => ({ ...prev, [part.key]: event.target.value })); setReviewed(false); }} placeholder="写下真实细节；不需要编造数字" />
          </label>)}</div>
          <div className={styles.reviewActions}><button type="button" onClick={() => setReviewed(true)}>检查结构</button><button type="button" className={styles.secondary} onClick={() => { setDraft(emptyDraft); setReviewed(false); }}>清空重写</button></div>
          {reviewed && <p className={styles.explanation} role="status">{missing.length ? `还可以补充：${starParts.filter((p) => missing.includes(p.key)).map((p) => p.title).join("、")}。尤其检查“行动”是否说明你本人做了什么。` : "四段都有内容。请再核对是否真实、是否回答了题目，以及行动和结果是否具体。填写完整不代表获得面试分数。"}</p>}
          {built && <div className={styles.preview}><h4>你的答案草稿</h4><p>{built}</p></div>}
        </div>
      </section>
      <aside className={styles.sources} aria-label="延伸阅读">
        <strong>延伸阅读</strong>
        <a href="https://career.berkeley.edu/prepare-for-success/interviewing/" target="_blank" rel="noopener noreferrer">加州大学伯克利分校 · 面试准备</a>
        <a href="https://careerservices.fas.harvard.edu/resources/interviewing/" target="_blank" rel="noopener noreferrer">哈佛大学职业中心 · 面试与提问</a>
      </aside>
      <footer className={styles.footer}><Link href="/">带着这段回答去练习面试 →</Link><p>学习方法供训练使用；面试与最终报告以实际作答和系统评分为准。</p></footer>
    </main>
  );
}
