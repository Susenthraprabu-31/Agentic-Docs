import { BrowserRouter, Link, NavLink, Route, Routes, useLocation } from "react-router-dom";
import Home from "./pages/Home";
import RunDetail from "./pages/RunDetail";
import ReportView from "./pages/ReportView";
import BatchDashboard from "./pages/BatchDashboard";
import BatchDetailView from "./pages/BatchDetailView";

function Layout() {
  const location = useLocation();
  const isEditor = location.pathname === "/";

  return (
    <div className="min-h-screen flex flex-col bg-[#0a0e14]">
      <header className="bg-[#0c1017] border-b border-teal-900/40 px-6 py-2.5 shrink-0">
        <div className={`${isEditor ? "w-full" : "max-w-6xl mx-auto"} flex items-center justify-between`}>
          <div className="flex items-center gap-6">
            <Link to="/" className="font-bold text-teal-300 flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-teal-400" />
              Docs
            </Link>

            <nav className="flex items-center gap-1 text-xs">
              <NavLink
                to="/"
                className={({ isActive }) =>
                  `px-3 py-1.5 rounded-lg font-medium transition-colors ${
                    isActive
                      ? "bg-teal-950 text-teal-300 border border-teal-800"
                      : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/40"
                  }`
                }
              >
                Pipeline Canvas
              </NavLink>
              <NavLink
                to="/batches"
                className={({ isActive }) =>
                  `px-3 py-1.5 rounded-lg font-medium transition-colors flex items-center gap-1.5 ${
                    isActive
                      ? "bg-teal-950 text-teal-300 border border-teal-800"
                      : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/40"
                  }`
                }
              >
                <span>Batch Orders</span>
                <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-teal-900/60 text-teal-300">New</span>
              </NavLink>
            </nav>
          </div>

          <span className="text-xs text-zinc-600 hidden sm:inline">Node Pipeline & Batch Automation</span>
        </div>
      </header>

      <main className={isEditor ? "flex-1 min-h-0" : "max-w-6xl mx-auto px-6 py-8 w-full"}>
        <Routes>
          <Route path="/" element={<Home />} />
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
    <BrowserRouter>
      <Layout />
    </BrowserRouter>
  );
}
