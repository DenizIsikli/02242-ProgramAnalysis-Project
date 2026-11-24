package jpamb.cases;

/**
 * Extra pairs for the evaluation only (evaluation/ablation.py). They are not part of the
 * shared corpus: they stress the cases where the baselines differ, namely loops and many
 * paths. No @Case annotations; ground truth comes from exhaustive execution.
 */
public class EvalPairs {

  // --- loops --------------------------------------------------------------------------

  /** Original: sum 0..n-1, then divide by d. */
  public static int loopDiv(int n, int d) {
    int s = 0;
    for (int i = 0; i < n; i++) s += i;
    return s / d;
  }

  /** Edit adds a guard for d == 0: changes behaviour exactly where d == 0. */
  public static int loopDiv_guarded(int n, int d) {
    int s = 0;
    for (int i = 0; i < n; i++) s += i;
    if (d == 0) return 0;
    return s / d;
  }

  /** Same loop written with a different body expression; behaviour identical. */
  public static int loopDiv_rewritten(int n, int d) {
    int s = 0;
    for (int i = 0; i < n; i++) s = s + i;
    return s / d;
  }

  /** Loop then an unconditional division by zero. */
  public static int loopThenZero(int n) {
    int s = 0;
    for (int i = 0; i < n; i++) s += 2;
    return s / 0;
  }

  public static int loopThenZero_edited(int n) {
    int s = 0;
    for (int i = 0; i < n; i++) s += 3;
    return s / 0;
  }

  // --- many paths -----------------------------------------------------------------------

  public static int ladder(int x) {
    int s = 0;
    if (x > 1) s += 1;
    if (x > 2) s += 2;
    if (x > 3) s += 3;
    if (x > 4) s += 4;
    if (x > 5) s += 5;
    if (x > 6) s += 6;
    if (x > 7) s += 7;
    if (x > 8) s += 8;
    if (x > 9) s += 9;
    if (x > 10) s += 10;
    if (x > 11) s += 11;
    if (x > 12) s += 12;
    return s;
  }
  public static int ladder_reordered(int x) {
    int s = 0;
    if (x > 12) s += 12;
    if (x > 11) s += 11;
    if (x > 10) s += 10;
    if (x > 9) s += 9;
    if (x > 8) s += 8;
    if (x > 7) s += 7;
    if (x > 6) s += 6;
    if (x > 5) s += 5;
    if (x > 4) s += 4;
    if (x > 3) s += 3;
    if (x > 2) s += 2;
    if (x > 1) s += 1;
    return s;
  }
  public static int ladder_changed(int x) {
    int s = 0;
    if (x > 12) s += 12;
    if (x > 11) s += 11;
    if (x > 10) s += 10;
    if (x > 9) s += 9;
    if (x > 8) s += 8;
    if (x > 7) s += 7;
    if (x > 6) s += 7;
    if (x > 5) s += 5;
    if (x > 4) s += 4;
    if (x > 3) s += 3;
    if (x > 2) s += 2;
    if (x > 1) s += 1;
    return s;
  }
}
