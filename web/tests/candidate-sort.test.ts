import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { sortCandidatesByEducation } from "../lib/candidate-sort.ts";

describe("enterprise education sorting", () => {
  it("orders five education levels without mixing or losing candidates", () => {
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
});
