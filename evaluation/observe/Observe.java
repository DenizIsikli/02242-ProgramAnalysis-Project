import java.io.IOException;
import java.io.PrintWriter;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

/**
 * Reference observations for the behaviour-preservation corpus.
 *
 * <p>For every pair listed in pairs.txt, runs the original and the edited method on the real JVM
 * for every input in the declared domain, and writes one CSV per pair with the outcome and return
 * value of both versions. This deliberately does NOT use our analyser or interpreter: it is the
 * ground truth the analyser is checked against.
 *
 * <p>Usage: java -ea -cp <classes> Observe <pairs.txt> <output dir>
 */
public class Observe {

  static final Class<?> CASES = jpamb.cases.Refactorings.class;
  static final long TIMEOUT_MS = 1000;
  static final ExecutorService POOL = Executors.newCachedThreadPool(r -> {
    Thread t = new Thread(r);
    t.setDaemon(true); // lets the program exit even if a call never terminates
    return t;
  });

  /** Outcome name (JPAMB spelling) and return value ("" unless the outcome is ok). */
  record Result(String outcome, String ret) {}

  public static void main(String[] args) throws Exception {
    Path pairsFile = Path.of(args[0]);
    Path outDir = Path.of(args[1]);
    Files.createDirectories(outDir);

    for (String line : Files.readAllLines(pairsFile)) {
      line = line.strip();
      if (line.isEmpty() || line.startsWith("#")) continue;
      String[] f = line.split("\\s+");
      observePair(f[0], Integer.parseInt(f[1]), Integer.parseInt(f[2]), outDir);
    }
  }

  static void observePair(String name, int low, int high, Path outDir) throws IOException {
    Method orig = findMethod(name);
    Method edited = findMethod(name + "_edited");
    int arity = orig.getParameterCount();
    if (edited.getParameterCount() != arity) {
      throw new IllegalStateException(name + ": versions take different numbers of arguments");
    }
    for (Class<?> p : orig.getParameterTypes()) {
      if (p != int.class) throw new IllegalStateException(name + ": only int parameters supported");
    }

    Path out = outDir.resolve(name + ".csv");
    int differing = 0, total = 0;
    try (PrintWriter w = new PrintWriter(Files.newBufferedWriter(out))) {
      List<String> header = new ArrayList<>();
      for (var p : orig.getParameters()) header.add(p.getName());
      header.addAll(List.of("orig_outcome", "orig_return", "edited_outcome", "edited_return", "same"));
      w.println(String.join(",", header));

      for (int[] input : allInputs(arity, low, high)) {
        Result r1 = run(orig, input);
        Result r2 = run(edited, input);
        boolean same = r1.equals(r2);
        if (!same) differing++;
        total++;

        List<String> row = new ArrayList<>();
        for (int v : input) row.add(Integer.toString(v));
        row.addAll(List.of(r1.outcome(), r1.ret(), r2.outcome(), r2.ret(), same ? "yes" : "no"));
        w.println(String.join(",", row));
      }
    }
    System.out.printf("%-10s %3d inputs, %3d differ -> %s%n", name, total, differing, out);
  }

  /** Runs one method on one input and classifies what happened. */
  static Result run(Method m, int[] input) {
    Object[] args = new Object[input.length];
    for (int i = 0; i < input.length; i++) args[i] = input[i];

    Future<Object> call = POOL.submit(() -> m.invoke(null, args));
    try {
      Object value = call.get(TIMEOUT_MS, TimeUnit.MILLISECONDS);
      return new Result("ok", String.valueOf(value));
    } catch (TimeoutException e) {
      call.cancel(true);
      return new Result("*", ""); // treated as non-termination
    } catch (ExecutionException e) {
      Throwable t = e.getCause();
      if (t instanceof InvocationTargetException ite) t = ite.getCause();
      return new Result(classify(t), "");
    } catch (InterruptedException e) {
      throw new RuntimeException(e);
    }
  }

  /** Maps a Java exception to JPAMB's outcome names. */
  static String classify(Throwable t) {
    if (t instanceof ArithmeticException) return "divide by zero";
    if (t instanceof AssertionError) return "assertion error";
    if (t instanceof ArrayIndexOutOfBoundsException) return "out of bounds";
    if (t instanceof NullPointerException) return "null pointer";
    throw new IllegalStateException("Unexpected exception: " + t, t);
  }

  static Method findMethod(String name) {
    for (Method m : CASES.getDeclaredMethods()) {
      if (m.getName().equals(name)) return m;
    }
    throw new IllegalArgumentException("No method " + name + " in " + CASES.getName());
  }

  /** Every int vector of the given length with entries in [low, high]. */
  static List<int[]> allInputs(int arity, int low, int high) {
    List<int[]> result = new ArrayList<>();
    result.add(new int[0]);
    for (int i = 0; i < arity; i++) {
      List<int[]> next = new ArrayList<>();
      for (int[] prefix : result) {
        for (int v = low; v <= high; v++) {
          int[] longer = java.util.Arrays.copyOf(prefix, prefix.length + 1);
          longer[prefix.length] = v;
          next.add(longer);
        }
      }
      result = next;
    }
    return result;
  }
}
