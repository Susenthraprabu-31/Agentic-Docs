import { useTheme } from "../../context/ThemeContext";

interface Props {
  className?: string;
  showLabel?: boolean;
}

export default function ThemeToggle({ className = "", showLabel = false }: Props) {
  const { theme, isDark, toggleTheme } = useTheme();

  return (
    <button
      type="button"
      onClick={toggleTheme}
      className={`relative inline-flex items-center w-[52px] h-7 rounded-full p-0.5 transition-all duration-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-500 select-none shrink-0 cursor-pointer ${
        isDark
          ? "bg-zinc-800/90 border border-white/[0.1] text-zinc-300 hover:text-white hover:border-white/[0.2]"
          : "bg-slate-200/90 border border-slate-300 text-slate-700 hover:text-slate-900 hover:border-slate-400"
      } ${className}`}
      title={isDark ? "Switch to Day Theme (Light)" : "Switch to Dark Theme"}
      aria-label={isDark ? "Switch to Day Theme (Light)" : "Switch to Dark Theme"}
    >
      {/* Background static icons for track */}
      <div className="w-full flex items-center justify-between px-1.5 pointer-events-none absolute inset-0 text-[10px]">
        <span
          className={`flex items-center justify-center w-5 h-5 transition-opacity duration-200 ${
            isDark ? "opacity-0" : "opacity-40 text-slate-500"
          }`}
        >
          <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
            <path d="M17.293 13.293A8 8 0 016.707 2.707a8.001 8.001 0 1010.586 10.586z" />
          </svg>
        </span>
        <span
          className={`flex items-center justify-center w-5 h-5 transition-opacity duration-200 ${
            isDark ? "opacity-40 text-zinc-400" : "opacity-0"
          }`}
        >
          <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z"
            />
          </svg>
        </span>
      </div>

      {/* Sliding indicator pill */}
      <div
        className={`w-5 h-5 rounded-full flex items-center justify-center transition-transform duration-300 shadow-md relative z-10 ${
          isDark
            ? "translate-x-0.5 bg-zinc-900 text-amber-300 shadow-black/50 border border-amber-400/20"
            : "translate-x-[25px] bg-white text-amber-500 shadow-slate-400/40 border border-amber-300/40"
        }`}
      >
        {isDark ? (
          // Moon icon
          <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
            <path d="M17.293 13.293A8 8 0 016.707 2.707a8.001 8.001 0 1010.586 10.586z" />
          </svg>
        ) : (
          // Sun icon
          <svg className="w-3 h-3 text-amber-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z"
            />
          </svg>
        )}
      </div>

      {showLabel && (
        <span className="ml-2 text-xs font-semibold select-none pr-1">
          {isDark ? "Dark" : "Day"}
        </span>
      )}
    </button>
  );
}
