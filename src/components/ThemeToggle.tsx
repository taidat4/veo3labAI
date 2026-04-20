/**
 * ThemeToggle — Sun/Moon animated toggle button
 */
"use client";
import { useState, useEffect, useCallback } from "react";

export function ThemeToggle() {
  const [isDark, setIsDark] = useState(true);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    // Read from localStorage on mount
    const stored = localStorage.getItem("veo3_theme");
    const hasDarkClass = document.documentElement.classList.contains("dark");
    setIsDark(stored ? stored === "dark" : hasDarkClass);
    setMounted(true);
  }, []);

  const toggle = useCallback(() => {
    const next = !isDark;
    setIsDark(next);
    if (next) {
      document.documentElement.classList.add("dark");
    } else {
      document.documentElement.classList.remove("dark");
    }
    localStorage.setItem("veo3_theme", next ? "dark" : "light");
  }, [isDark]);

  // Don't render until mounted to avoid hydration mismatch
  if (!mounted) {
    return <div className="w-9 h-9" />;
  }

  return (
    <button
      id="theme-toggle"
      onClick={toggle}
      aria-label={isDark ? "Chuyển sang sáng" : "Chuyển sang tối"}
      title={isDark ? "Light mode" : "Dark mode"}
      className="relative w-9 h-9 rounded-full flex items-center justify-center transition-all duration-300 hover:scale-110"
      style={{
        background: "var(--bg-tertiary)",
        border: "1px solid var(--border-subtle)",
      }}
    >
      {/* Sun icon */}
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        className="absolute"
        style={{
          width: 18,
          height: 18,
          color: isDark ? "var(--text-muted)" : "#f59e0b",
          transform: isDark ? "rotate(-90deg) scale(0)" : "rotate(0) scale(1)",
          transition: "transform 0.4s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.3s, color 0.3s",
          opacity: isDark ? 0 : 1,
        }}
      >
        <circle cx="12" cy="12" r="5" />
        <line x1="12" y1="1" x2="12" y2="3" />
        <line x1="12" y1="21" x2="12" y2="23" />
        <line x1="4.22" y1="4.22" x2="5.64" y2="5.64" />
        <line x1="18.36" y1="18.36" x2="19.78" y2="19.78" />
        <line x1="1" y1="12" x2="3" y2="12" />
        <line x1="21" y1="12" x2="23" y2="12" />
        <line x1="4.22" y1="19.78" x2="5.64" y2="18.36" />
        <line x1="18.36" y1="5.64" x2="19.78" y2="4.22" />
      </svg>

      {/* Moon icon */}
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
        className="absolute"
        style={{
          width: 18,
          height: 18,
          color: isDark ? "#a78bfa" : "var(--text-muted)",
          transform: isDark ? "rotate(0) scale(1)" : "rotate(90deg) scale(0)",
          transition: "transform 0.4s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.3s, color 0.3s",
          opacity: isDark ? 1 : 0,
        }}
      >
        <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
      </svg>
    </button>
  );
}
