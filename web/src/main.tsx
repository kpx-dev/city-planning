import React from "react";
import ReactDOM from "react-dom/client";
import { HashRouter, Routes, Route } from "react-router-dom";
import App from "./App";
import { ProjectDetail } from "./components/ProjectDetail";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <HashRouter>
      <Routes>
        <Route path="/" element={<App />} />
        <Route path="/p/:caseNumber" element={<ProjectDetail />} />
      </Routes>
    </HashRouter>
  </React.StrictMode>
);
