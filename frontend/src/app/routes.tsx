import { createBrowserRouter } from "react-router";
import { AnimatedLayout } from "./components/AnimatedLayout";

export const router = createBrowserRouter([
  { path: "/", Component: AnimatedLayout },
  { path: "/onboarding", Component: AnimatedLayout },
  { path: "/chat", Component: AnimatedLayout },
]);
