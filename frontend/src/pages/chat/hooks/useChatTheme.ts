import { useCallback, useEffect, useState } from 'react';

function detectSystemDark(): boolean {
  return window.matchMedia('(prefers-color-scheme: dark)').matches;
}

function readStoredTheme(): boolean {
  const stored = localStorage.getItem('theme');
  return stored !== null ? stored === 'dark' : detectSystemDark();
}

function applyTheme(dark: boolean) {
  const theme = dark ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('theme', theme);
}

export function useChatTheme() {
  const [darkMode, setDarkMode] = useState(readStoredTheme);

  const toggleTheme = useCallback(() => {
    setDarkMode((prev) => !prev);
  }, []);

  useEffect(() => {
    applyTheme(darkMode);
  }, [darkMode]);

  return { darkMode, toggleTheme };
}
