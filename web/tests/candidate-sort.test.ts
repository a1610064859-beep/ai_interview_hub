import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  SORT_OPTIONS,
  filterCandidatesBySchoolNames,
  schoolNameOptions,
  sortCandidatesByEducation,
  sortCandidatesByOverall,
} from "../lib/candidate-sort.ts";

describe("enterprise candidate sorting options", () => {
  it("defines clear and unambiguous sort options", () => {
    assert.equal(SORT_OPTIONS.length, 3);
    assert.deepEqual(
      SORT_OPTIONS.map((o) => o.id),
      ["weighted_score", "education_level", "overall_score"]
    );
    assert.ok(SORT_OPTIONS.every((o) => o.label && o.desc));
  });

  it("orders five education levels by degree tier without mixing or losing candidates", () => {
    const candidates = [
      { user_id: 1, education_level: "中职" },
      { user_id: 2, education_level: "本科" },
      { user_id: 3, education_level: null },
      { user_id: 4, education_level: "博士" },
      { user_id: 5, education_level: "高职/大专" },
      { user_id: 6, education_level: "硕士" },
    ];
    assert.deepEqual(sortCandidatesByEducation(candidates, "desc").map((c) => c.user_id), [4, 6, 2, 5, 1, 3]);
    assert.deepEqual(sortCandidatesByEducation(candidates, "asc").map((c) => c.user_id), [1, 5, 2, 6, 4, 3]);
    assert.deepEqual(candidates.map((c) => c.user_id), [1, 2, 3, 4, 5, 6]);
  });

  it("sorts candidates by overall score descending, placing nulls at the end", () => {
    const candidates = [
      { user_id: 1, overall: 75.5 },
      { user_id: 2, overall: 88.0 },
      { user_id: 3, overall: null },
      { user_id: 4, overall: 92.3 },
      { user_id: 5, overall: 88.0 },
    ];
    const sorted = sortCandidatesByOverall(candidates);
    assert.deepEqual(
      sorted.map((c) => c.user_id),
      [4, 2, 5, 1, 3]
    );
  });
});

describe("school name checkbox filtering", () => {
  const candidates = [{ user_id: 3 }, { user_id: 1 }, { user_id: 2 }, { user_id: 4 }];
  const schools = { 1: "上海某职业院校", 2: "江苏某职业院校", 3: "上海某职业院校", 4: null };

  it("keeps all candidates when unchecked, and supports multiple school choices without reordering", () => {
    assert.deepEqual(filterCandidatesBySchoolNames(candidates, schools, []).map((candidate) => candidate.user_id), [3, 1, 2, 4]);
    assert.deepEqual(filterCandidatesBySchoolNames(candidates, schools, ["上海某职业院校"]).map((candidate) => candidate.user_id), [3, 1]);
    assert.deepEqual(filterCandidatesBySchoolNames(candidates, schools, ["江苏某职业院校", "上海某职业院校"]).map((candidate) => candidate.user_id), [3, 1, 2]);
    assert.deepEqual(candidates.map((candidate) => candidate.user_id), [3, 1, 2, 4]);
  });

  it("offers unique school names and an explicit unread-name option, without assigning school ranks", () => {
    assert.deepEqual(schoolNameOptions(candidates, schools), [{ name: "上海某职业院校", count: 2 }, { name: "江苏某职业院校", count: 1 }, { name: null, count: 1 }]);
    assert.deepEqual(filterCandidatesBySchoolNames(candidates, schools, [null]).map((candidate) => candidate.user_id), [4]);
    assert.deepEqual(filterCandidatesBySchoolNames([{ user_id: 5 }], {}, [null]), [{ user_id: 5 }]);
    assert.deepEqual(filterCandidatesBySchoolNames(candidates, schools, ["不存在的学校"]), []);
  });
});
