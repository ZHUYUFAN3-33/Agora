import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./app/App";
import { installFadeScrollbars } from "./app/fadeScrollbars";
import "./styles/index.css";

installFadeScrollbars();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
