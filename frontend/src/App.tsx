import { BrowserRouter, Route, Routes } from "react-router-dom";
import Home from "./pages/Home";
import RunDetail from "./pages/RunDetail";
import ReportView from "./pages/ReportView";

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen">
        <header className="bg-white border-b border-slate-200 px-6 py-4">
          <div className="max-w-5xl mx-auto flex items-center justify-between">
            <span className="font-bold text-slate-800">Docs</span>
            <span className="text-xs text-slate-400">All US States · NETR Online</span>
          </div>
        </header>
        <main className="max-w-5xl mx-auto px-6 py-8">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/runs/:runId" element={<RunDetail />} />
            <Route path="/reports/run/:runId" element={<ReportView />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}
