// The one random stream every module draws from, like the Python port's
// use of the `random` module (seed it to reproduce a run).

import { PyRandom } from './pymath.js';

let current = new PyRandom(Date.now());

const rng = {
  seed(n) {
    current = new PyRandom(n);
  },
  random() {
    return current.random();
  },
  randrange(n) {
    return current.randrange(n);
  },
};

export { rng };
