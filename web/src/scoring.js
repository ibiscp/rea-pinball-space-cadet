// Port of scoring.py: point values from the original's control table at
// 0x1023ef0 (see that module for the evidence).

const SCORES = new Map();

function set(names, scores) {
  for (const n of names) SCORES.set(n, scores);
}

set([1, 2, 3, 4].map((i) => `a_bump${i}`), [500, 1000, 1500, 2000]);
set([5, 6, 7].map((i) => `a_bump${i}`), [1500, 2500, 3500, 4500]);
set([1, 2, 3].map((i) => `a_roll${i}`), [2000]);
set([110, 111, 112].map((i) => `a_roll${i}`), [500]);
set([4, 8].map((i) => `a_roll${i}`), [20000]);
set([6, 7].map((i) => `a_roll${i}`), [5000, 25000]);
SCORES.set('a_roll5', [10000]);
SCORES.set('a_roll9', [10000]);
set([179, 180, 181, 182, 183, 184].map((i) => `a_roll${i}`), [500]);
set([1, 2, 3, 4].map((i) => `v_rebo${i}`), [500]);
SCORES.set('ramp', [5000]);
SCORES.set('s_onewy4', [15000, 30000, 75000, 30000, 15000, 7500]);
SCORES.set('a_flag1', [500, 2500]);
SCORES.set('a_flag2', [500, 2500]);
SCORES.set('a_kout1', [50000]);
SCORES.set('a_kout2', [10000, 0, 20000, 50000, 150000]);
SCORES.set('a_kout3', [20000]);
set([1, 2, 3].map((i) => `v_sink${i}`), [2500, 5000, 7500]);
set([1, 2, 3].map((i) => `a_targ${i}`), [500, 5000]);
set([4, 5, 6].map((i) => `a_targ${i}`), [1500, 10000, 50000]);
set([7, 8, 9].map((i) => `a_targ${i}`), [500, 1500]);
set([10, 11, 12].map((i) => `a_targ${i}`), [750]);
set([13, 14, 15].map((i) => `a_targ${i}`), [1000]);
set([16, 17, 18, 19, 20, 21, 22].map((i) => `a_targ${i}`), [750]);

export { SCORES };
