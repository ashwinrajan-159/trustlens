import { Routes, Route, Navigate } from "react-router-dom";
import Layout, { ProtectedRoute, AnalystRoute } from "./components/Layout";
import Landing from "./pages/Landing";
import Login from "./pages/Login";
import Register from "./pages/Register";
import Dashboard from "./pages/Dashboard";
import Apply from "./pages/Apply";
import Applications from "./pages/Applications";
import AppDetail from "./pages/AppDetail";
import ReviewQueue from "./pages/ReviewQueue";
import AnalystReview from "./pages/AnalystReview";
import Alerts from "./pages/Alerts";
import Cases from "./pages/Cases";
import Operations from "./pages/Operations";
import MLPlatform from "./pages/MLPlatform";
import NetworkGraph from "./pages/NetworkGraph";
import Account from "./pages/Account";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />

      <Route path="/app" element={<ProtectedRoute />}>
        <Route element={<Layout />}>
          <Route index element={<Navigate to="dashboard" replace />} />
          <Route path="dashboard" element={<Dashboard />} />
          <Route path="apply" element={<Apply />} />
          <Route path="applications" element={<Applications />} />
          <Route path="applications/:id" element={<AppDetail />} />
          <Route path="network/:id" element={<NetworkGraph />} />
          <Route path="account" element={<Account />} />

          {/* Analyst-only cluster */}
          <Route element={<AnalystRoute />}>
            <Route path="review-queue" element={<ReviewQueue />} />
            <Route path="review/:id" element={<AnalystReview />} />
            <Route path="alerts" element={<Alerts />} />
            <Route path="cases" element={<Cases />} />
            <Route path="operations" element={<Operations />} />
            <Route path="ml" element={<MLPlatform />} />
          </Route>
        </Route>
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
