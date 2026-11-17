import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { AppShell } from "./AppShell";

export function ProtectedRoute() {
  const { user, loading } = useAuth();
  if (loading) return <div className="center-screen"><div className="spinner"/><p>Opening your workspace…</p></div>;
  if (!user) return <Navigate to="/login" replace />;
  return <AppShell><Outlet /></AppShell>;
}
