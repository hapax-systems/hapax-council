import { useState, useCallback, useRef } from "react";

export function useInputHistory(maxSize = 50) {
  const historyRef = useRef<string[]>([]);
  const [index, setIndex] = useState(-1);
  const [savedInput, setSavedInput] = useState("");

  const addEntry = useCallback((text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    // Deduplicate with last entry
    if (historyRef.current[historyRef.current.length - 1] !== trimmed) {
      historyRef.current.push(trimmed);
      if (historyRef.current.length > maxSize) {
        historyRef.current.shift();
      }
    }
    setIndex(-1);
    setSavedInput("");
  }, [maxSize]);

  const navigateUp = useCallback((currentInput: string): string | null => {
    if (historyRef.current.length === 0) return null;

    if (index === -1) {
      setSavedInput(currentInput);
      const newIndex = historyRef.current.length - 1;
      setIndex(newIndex);
      return historyRef.current[newIndex];
    }

    if (index > 0) {
      const newIndex = index - 1;
      setIndex(newIndex);
      return historyRef.current[newIndex];
    }

    return null; // Already at oldest
  }, [index]);

  const navigateDown = useCallback((): string | null => {
    if (index === -1) return null;

    if (index < historyRef.current.length - 1) {
      const newIndex = index + 1;
      setIndex(newIndex);
      return historyRef.current[newIndex];
    }

    // Back to current input
    setIndex(-1);
    return savedInput;
  }, [index, savedInput]);

  const reset = useCallback(() => {
    setIndex(-1);
    setSavedInput("");
  }, []);

  return { addEntry, navigateUp, navigateDown, reset };
}
