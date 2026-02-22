import { createBrowserRouter } from "react-router";
import Landing from "./pages/Landing";
import Onboarding from "./pages/Onboarding";
import Chat from "./pages/Chat";

export const router = createBrowserRouter([
  { path: "/", Component: Landing },
  { path: "/onboarding", Component: Onboarding },
  { path: "/chat", Component: Chat },
]);
