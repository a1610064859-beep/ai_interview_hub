import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  countPauses,
  levelToUnit,
  SILENCE_DB_THRESHOLD,
  SILENCE_RUN_SECONDS,
} from "../lib/recorder.ts";

const LOUD = -20; // 明显有声
const QUIET = -55; // 低于 -45dB 阈值的静音

function samples(count: number, db: number): number[] {
  return Array.from({ length: count }, () => db);
}

describe("countPauses（AGENTS §6.3：<-45dB 持续 >1.5s 计 1 次停顿）", () => {
  it("全程有声 → 0 次停顿", () => {
    assert.equal(countPauses(samples(50, LOUD), 0.1), 0);
  });

  it("静音但未超过 1.5s → 0 次停顿", () => {
    // 1.4s 静音（14 个 0.1s 采样）
    const seq = [...samples(5, LOUD), ...samples(14, QUIET), ...samples(5, LOUD)];
    assert.equal(countPauses(seq, 0.1), 0);
  });

  it("恰好 1.5s 静音不计数（阈值是严格大于）", () => {
    const seq = [...samples(5, LOUD), ...samples(15, QUIET), ...samples(5, LOUD)];
    assert.equal(countPauses(seq, 0.1), 0);
  });

  it("超过 1.5s 的静音 → 1 次停顿", () => {
    const seq = [...samples(5, LOUD), ...samples(16, QUIET), ...samples(5, LOUD)];
    assert.equal(countPauses(seq, 0.1), 1);
  });

  it("一段很长的静音只计 1 次（不重复累计）", () => {
    const seq = [...samples(5, LOUD), ...samples(80, QUIET), ...samples(5, LOUD)];
    assert.equal(countPauses(seq, 0.1), 1);
  });

  it("两段独立静音 → 2 次停顿", () => {
    const seq = [
      ...samples(5, LOUD),
      ...samples(20, QUIET),
      ...samples(8, LOUD),
      ...samples(20, QUIET),
      ...samples(5, LOUD),
    ];
    assert.equal(countPauses(seq, 0.1), 2);
  });

  it("阈值边界：-45dB 本身不算静音（严格小于）", () => {
    const seq = [...samples(5, LOUD), ...samples(30, SILENCE_DB_THRESHOLD), ...samples(5, LOUD)];
    assert.equal(countPauses(seq, 0.1), 0);
  });

  it("非法采样间隔 → 0", () => {
    assert.equal(countPauses(samples(10, QUIET), 0), 0);
    assert.equal(countPauses(samples(10, QUIET), -0.1), 0);
  });

  it("阈值与时长常量与 AGENTS §6.3 一致", () => {
    assert.equal(SILENCE_DB_THRESHOLD, -45);
    assert.equal(SILENCE_RUN_SECONDS, 1.5);
  });
});

describe("levelToUnit（电平环归一化）", () => {
  it("映射 -60..0 dB → 0..1", () => {
    assert.equal(levelToUnit(-60), 0);
    assert.equal(levelToUnit(-30), 0.5);
    assert.equal(levelToUnit(0), 1);
  });

  it("越界值被钳制", () => {
    assert.equal(levelToUnit(-120), 0);
    assert.equal(levelToUnit(10), 1);
  });
});
