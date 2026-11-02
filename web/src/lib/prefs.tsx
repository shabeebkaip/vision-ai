import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import type { Digits, FormatOptions, Lang } from './format';
import * as f from './format';
import { DEFAULT_TZ } from './time';

const DIGITS_KEY = 'vision.digits';

function storedDigits(): Digits {
  try {
    return localStorage.getItem(DIGITS_KEY) === 'arab' ? 'arab' : 'latn';
  } catch {
    return 'latn';
  }
}

interface PrefsValue {
  digits: Digits;
  setDigits: (d: Digits) => void;
}

const PrefsContext = createContext<PrefsValue>({ digits: 'latn', setDigits: () => undefined });

export function PrefsProvider({
  children,
  initialDigits,
}: {
  children: ReactNode;
  initialDigits?: Digits;
}) {
  const [digits, setDigitsState] = useState<Digits>(initialDigits ?? storedDigits);
  const setDigits = useCallback((d: Digits) => {
    setDigitsState(d);
    try {
      localStorage.setItem(DIGITS_KEY, d);
    } catch {
      /* storage blocked */
    }
  }, []);
  const value = useMemo(() => ({ digits, setDigits }), [digits, setDigits]);
  return <PrefsContext.Provider value={value}>{children}</PrefsContext.Provider>;
}

export function usePrefs(): PrefsValue {
  return useContext(PrefsContext);
}

/** Formatters bound to the current language, digit style and site timezone. */
export function useFormat(tz: string = DEFAULT_TZ) {
  const { i18n } = useTranslation();
  const { digits } = usePrefs();
  const lang: Lang = i18n.language === 'ar' ? 'ar' : 'en';
  return useMemo(() => {
    const o: FormatOptions = { lang, digits, tz };
    return {
      opts: o,
      lang,
      number: (n: number, opts?: Intl.NumberFormatOptions) => f.fmtNumber(n, o, opts),
      percent: (r: number) => f.fmtPercent(r, o),
      dateTime: (iso: string) => f.fmtDateTime(iso, o),
      dateTimeSeconds: (iso: string) => f.fmtDateTimeSeconds(iso, o),
      time: (iso: string | Date) => f.fmtTime(iso, o),
      day: (iso: string) => f.fmtDay(iso, o),
      relative: (iso: string, now: Date = new Date()) => f.fmtRelative(iso, now, o),
      clock: (t: string) => f.fmtClock(t, o),
    };
  }, [lang, digits, tz]);
}
