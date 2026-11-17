import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { AuthPage } from "./pages/AuthPage";
import { DashboardPage } from "./pages/DashboardPage";
import { DocumentsPage } from "./pages/DocumentsPage";
import { MonitoringPage } from "./pages/MonitoringPage";
import { TutorPage } from "./pages/TutorPage";
import { WorkspacePage } from "./pages/WorkspacePage";

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 10_000 } } });

export default function App() {
  return <QueryClientProvider client={queryClient}><BrowserRouter><AuthProvider><Routes><Route path="/login" element={<AuthPage/>}/><Route path="/register" element={<AuthPage register/>}/><Route element={<ProtectedRoute/>}><Route index element={<DashboardPage/>}/><Route path="documents" element={<DocumentsPage/>}/><Route path="tutor" element={<TutorPage/>}/><Route path="workspace" element={<WorkspacePage/>}/><Route path="monitoring" element={<MonitoringPage/>}/></Route><Route path="*" element={<Navigate to="/" replace/>}/></Routes></AuthProvider></BrowserRouter></QueryClientProvider>;
}
