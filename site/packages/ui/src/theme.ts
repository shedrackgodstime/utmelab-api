/**
 * @utmelab/ui — theme controller (the ONE theme system for all surfaces).
 *
 * Contract shared with Starlight (NOTES §4, §3):
 *   - attribute : `data-theme` on <html>   → 'light' | 'dark'
 *   - storage   : localStorage key 'starlight-theme'
 *   - default   : OS `prefers-color-scheme`, then stored choice wins
 *
 * Because web + docs + app all read/write the same key + attribute,
 * toggling on any surface carries across the whole domain, and Starlight's
 * own built-in toggle stays in sync. Zero-JS by default; this module only
 * runs when a ThemeToggle is present.
 */

export type Theme = 'light' | 'dark';
const STORAGE_KEY = 'starlight-theme';

export function getStoredTheme(): Theme | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === 'light' || v === 'dark' ? v : null;
  } catch {
    return null;
  }
}

export function getPreferredTheme(): Theme {
  const stored = getStoredTheme();
  if (stored) return stored;
  if (typeof matchMedia === 'function' && matchMedia('(prefers-color-scheme: light)').matches) {
    return 'light';
  }
  return 'dark';
}

export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  root.setAttribute('data-theme', theme);
  // Keep the CSS color-scheme in sync so form controls/scrollbars match.
  root.style.colorScheme = theme;
  try {
    localStorage.setItem(STORAGE_KEY, theme);
  } catch {
    /* private mode — ignore */
  }
}

/** Flip to the opposite theme, persist, and return the new value. */
export function toggleTheme(): Theme {
  const next: Theme = getPreferredTheme() === 'dark' ? 'light' : 'dark';
  applyTheme(next);
  return next;
}

/** Sync every on-page toggle's pressed/icon state to the active theme. */
export function syncToggles(): void {
  const theme = document.documentElement.getAttribute('data-theme') as Theme | null;
  document.querySelectorAll<HTMLElement>('[data-theme-toggle]').forEach((btn) => {
    const isDark = theme === 'dark';
    btn.setAttribute('aria-pressed', String(isDark));
    btn.setAttribute('aria-label', isDark ? 'Switch to light theme' : 'Switch to dark theme');
    btn.title = isDark ? 'Switch to light theme' : 'Switch to dark theme';
  });
}

/**
 * Initialize: apply the correct theme ASAP (before paint where possible) and
 * wire up every [data-theme-toggle] button. Idempotent.
 */
export function initTheme(): void {
  applyTheme(getPreferredTheme());
  syncToggles();
  document.querySelectorAll<HTMLElement>('[data-theme-toggle]').forEach((btn) => {
    if (btn.dataset.themeBound === 'true') return;
    btn.dataset.themeBound = 'true';
    btn.addEventListener('click', () => {
      toggleTheme();
      syncToggles();
    });
  });
  // React to OS changes only while the user hasn't made an explicit choice.
  if (typeof matchMedia === 'function') {
    matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
      if (!getStoredTheme()) {
        applyTheme(getPreferredTheme());
        syncToggles();
      }
    });
  }
}
