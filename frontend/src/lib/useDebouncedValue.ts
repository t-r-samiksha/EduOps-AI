import { useEffect, useState } from "react";

/** Delays reflecting `value`'s changes by `delayMs` - used to avoid firing a
 * network request (e.g. live pre-flight validation) on every keystroke. */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}
