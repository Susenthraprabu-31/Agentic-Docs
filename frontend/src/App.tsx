import { BrowserRouter, Route, Routes, useLocation } from "react-router-dom";
import Home from "./pages/Home";
import RunDetail from "./pages/RunDetail";
import ReportView from "./pages/ReportView";
import BatchDashboard from "./pages/BatchDashboard";
import BatchDetailView from "./pages/BatchDetailView";
import { ThemeProvider } from "./context/ThemeContext";
import ThemeToggle from "./components/common/ThemeToggle";

/** Thin wrapper — the pipeline editor is full-screen and owns its own layout.
 *  Non-editor pages still get a simple header nav. */
function Layout() {
  const location = useLocation();
  const isEditor = location.pathname === "/";

  if (isEditor) {
    // Full-screen — PipelineEditor handles all chrome
    return (
      <Routes>
        <Route path="/" element={<Home />} />
      </Routes>
    );
  }

  return (
    <div className="min-h-screen flex flex-col bg-slate-50 dark:bg-[#0d1117] text-slate-900 dark:text-zinc-100 transition-colors">
      {/* Minimal header for non-editor pages */}
      <header className="bg-white dark:bg-[#0d1117] border-b border-slate-200 dark:border-white/[0.06] px-6 py-3 shrink-0">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-4">
            <a href="/" className="font-bold text-violet-600 dark:text-violet-400 flex items-center gap-2 text-sm">
              <span className="w-6 h-6 rounded-md bg-violet-600 flex items-center justify-center">
                <svg className="w-3.5 h-3.5 text-white" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M8 5v14l11-7z" />
                </svg>
              </span>
              Docs
            </a>
            <nav className="flex items-center gap-1 text-xs">
              <a
                href="/"
                className="px-3 py-1.5 rounded-lg text-slate-600 hover:text-slate-900 hover:bg-slate-100 dark:text-zinc-400 dark:hover:text-zinc-200 dark:hover:bg-zinc-800/40 transition-colors font-medium"
              >
                Pipeline Canvas
              </a>
              <a
                href="/batches"
                className="px-3 py-1.5 rounded-lg text-slate-600 hover:text-slate-900 hover:bg-slate-100 dark:text-zinc-400 dark:hover:text-zinc-200 dark:hover:bg-zinc-800/40 transition-colors font-medium flex items-center gap-1.5"
              >
                Batch Orders
                <span className="px-1.5 py-0.5 rounded-full text-[9px] bg-violet-100 dark:bg-violet-900/60 text-violet-700 dark:text-violet-300 font-bold">
                  New
                </span>
              </a>
            </nav>
          </div>

          <div className="flex items-center gap-3">
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-6 py-8 w-full">
        <Routes>
          <Route path="/batches" element={<BatchDashboard />} />
          <Route path="/batches/:batchId" element={<BatchDetailView />} />
          <Route path="/runs/:runId" element={<RunDetail />} />
          <Route path="/reports/run/:runId" element={<ReportView />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <Layout />
      </BrowserRouter>
    </ThemeProvider>
  );
}
