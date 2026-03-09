import { RouterProvider } from "react-router";
import { router } from "./routes";
import "../styles/fonts.css";
import { AppearanceProvider } from "./context/AppearanceContext";

export default function App() {
  return (
    <AppearanceProvider>
      <RouterProvider router={router} />
    </AppearanceProvider>
  );
}
