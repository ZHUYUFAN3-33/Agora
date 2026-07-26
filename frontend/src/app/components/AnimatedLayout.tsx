import React, { type ComponentType } from "react";
import { useLocation } from "react-router";
import { AnimatePresence, motion } from "motion/react";
import Landing from "../pages/Landing";
import Onboarding from "../pages/Onboarding";
import Chat from "../pages/Chat";
import Admin from "../pages/Admin";

const ROUTES: Record<string, ComponentType> = {
  "/": Landing,
  "/onboarding": Onboarding,
  "/chat": Chat,
  "/admin": Admin,
};

export function AnimatedLayout() {
  const location = useLocation();
  const Page: ComponentType = ROUTES[location.pathname] ?? Landing;

  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div
        key={location.pathname}
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -6 }}
        transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
      >
        <Page />
      </motion.div>
    </AnimatePresence>
  );
}
