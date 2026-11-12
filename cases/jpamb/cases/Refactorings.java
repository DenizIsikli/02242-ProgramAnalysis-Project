package jpamb.cases;

import jpamb.utils.Case;

/**
 * Paired methods for the behaviour-preservation corpus.
 *
 * <p>Each pair is an original method {@code m} and an edited version {@code m_edited} in this
 * class. The {@code @Case} annotations record outcomes only (as in the rest of JPAMB); return
 * values are recorded separately by evaluation/observe/Observe.java.
 */
public class Refactorings {

  // ---------------------------------------------------------------------------
  // Pair 1: unchanged. The edit inlines a temporary variable. Both versions
  // behave identically on every input.
  // ---------------------------------------------------------------------------

  @Case("(3, 2) -> ok")
  @Case("(3, 0) -> ok")
  public static int safeDiv(int a, int b) {
    if (b == 0) return 0;
    int q = a / b;
    return q;
  }

  @Case("(3, 2) -> ok")
  @Case("(3, 0) -> ok")
  public static int safeDiv_edited(int a, int b) {
    if (b == 0) return 0;
    return a / b;
  }

  // ---------------------------------------------------------------------------
  // Pair 2: faulty guard removal (Listing 1 of the proposal). The guard looks
  // redundant because 0 / x == 0, but without it (0, 0) divides by zero.
  // Note that the ORIGINAL also divides by zero when max(a, b) == 0 and a != b,
  // e.g. (0, -1); both versions agree on those inputs.
  // ---------------------------------------------------------------------------

  @Case("(0, 0) -> ok")
  @Case("(1, 2) -> ok")
  @Case("(0, -1) -> divide by zero")
  public static int ratio(int a, int b) {
    int d = b - a;
    if (d == 0) return 0;
    return d / (a > b ? a : b);
  }

  @Case("(0, 0) -> divide by zero")
  @Case("(1, 2) -> ok")
  @Case("(0, -1) -> divide by zero")
  public static int ratio_edited(int a, int b) {
    int d = b - a;
    return d / (a > b ? a : b);
  }

  // ---------------------------------------------------------------------------
  // Pair 3: return-value-only change. The edit drops the x == 0 case. Both
  // versions always finish normally (same outcome set {ok}), but at x == 0 the
  // original returns 0 and the edited version returns -1.
  // ---------------------------------------------------------------------------

  @Case("(1) -> ok")
  @Case("(0) -> ok")
  @Case("(-1) -> ok")
  public static int sign(int x) {
    if (x > 0) return 1;
    if (x < 0) return -1;
    return 0;
  }

  @Case("(1) -> ok")
  @Case("(0) -> ok")
  @Case("(-1) -> ok")
  public static int sign_edited(int x) {
    if (x > 0) return 1;
    return -1;
  }
}
