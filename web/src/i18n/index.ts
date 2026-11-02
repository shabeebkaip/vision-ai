import i18n, { type i18n as I18n } from 'i18next';
import { initReactI18next } from 'react-i18next';
import ar from './ar.json';
import en from './en.json';

export const LANGS = ['en', 'ar'] as const;
export type AppLang = (typeof LANGS)[number];
export const resources = { en: { translation: en }, ar: { translation: ar } } as const;

const LANG_KEY = 'vision.lang';

export function storedLang(): AppLang {
  try {
    const v = localStorage.getItem(LANG_KEY);
    if (v === 'ar' || v === 'en') return v;
  } catch {
    /* storage blocked */
  }
  return 'en';
}

export function rememberLang(lang: AppLang): void {
  try {
    localStorage.setItem(LANG_KEY, lang);
  } catch {
    /* storage blocked */
  }
}

/** Sets lang and dir on <html> so Tailwind's logical utilities and rtl: variants flip. */
export function applyDocumentDirection(lang: string): void {
  if (typeof document === 'undefined') return;
  document.documentElement.lang = lang;
  document.documentElement.dir = i18n.dir(lang);
}

/** A standalone instance, used by tests and the app alike. */
export function createI18n(lng: AppLang = 'en'): I18n {
  const instance = i18n.createInstance();
  void instance.use(initReactI18next).init({
    resources,
    lng,
    fallbackLng: false,
    supportedLngs: [...LANGS],
    interpolation: { escapeValue: false },
    returnNull: false,
    initAsync: false,
  });
  return instance;
}

export function initAppI18n(): I18n {
  const instance = createI18n(storedLang());
  applyDocumentDirection(instance.language);
  instance.on('languageChanged', (lng) => {
    applyDocumentDirection(lng);
    rememberLang(lng === 'ar' ? 'ar' : 'en');
  });
  return instance;
}
