import { useCallback, useEffect, useRef, useState } from "react";

/* The Web Speech API isn't in TypeScript's DOM types yet; this is the part we use. */
type Recognition = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
};
type RecognitionClass = new () => Recognition;

function recognitionClass(): RecognitionClass | null {
  const w = window as unknown as { SpeechRecognition?: RecognitionClass; webkitSpeechRecognition?: RecognitionClass };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export const canListen = typeof window !== "undefined" && recognitionClass() !== null;
export const canSpeak = typeof window !== "undefined" && "speechSynthesis" in window;

/**
 * Hold to talk: start() while the button is held, stop() on release; `onDone` gets
 * the whole transcript. The words appear in `heard` as they are recognised.
 */
export function useListen(onDone: (text: string) => void) {
  const [listening, setListening] = useState(false);
  const [heard, setHeard] = useState("");
  const [error, setError] = useState<string | null>(null);
  const recognition = useRef<Recognition | null>(null);
  const text = useRef("");
  const done = useRef(onDone);
  useEffect(() => {
    done.current = onDone;
  });

  const start = useCallback(() => {
    const Klass = recognitionClass();
    if (!Klass || recognition.current) return;
    const r = new Klass();
    r.lang = "en-IN";
    r.interimResults = true;
    r.continuous = true;
    text.current = "";
    setHeard("");
    setError(null);
    r.onresult = (event) => {
      text.current = Array.from(event.results, (result) => result[0]?.transcript ?? "").join(" ").trim();
      setHeard(text.current);
    };
    r.onerror = (event) => {
      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        setError("Allow the microphone for this site to talk to Dayline.");
      } else if (event.error !== "aborted" && event.error !== "no-speech") {
        setError("Didn't catch that. Try again, or type instead.");
      }
    };
    r.onend = () => {
      recognition.current = null;
      setListening(false);
      setHeard("");
      if (text.current) done.current(text.current);
    };
    recognition.current = r;
    try {
      r.start();
      setListening(true);
    } catch {
      recognition.current = null;
    }
  }, []);

  const stop = useCallback(() => recognition.current?.stop(), []);

  useEffect(() => () => recognition.current?.abort(), []);
  return { listening, heard, error, start, stop };
}

/** Read at most the first two sentences aloud. */
export function speak(text: string) {
  if (!canSpeak) return;
  const short = (text.match(/[^.!?]+[.!?]+/g) ?? [text]).slice(0, 2).join(" ").trim();
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(short);
  utterance.lang = "en-IN";
  window.speechSynthesis.speak(utterance);
}

export function stopSpeaking() {
  if (canSpeak) window.speechSynthesis.cancel();
}
