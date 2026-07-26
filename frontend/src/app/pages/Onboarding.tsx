import React, { useEffect } from "react";
import { useNavigate } from "react-router";
import { getAuth } from "../auth";

/** Nickname onboarding removed — User ID is set at register/login. */
export default function Onboarding() {
  const navigate = useNavigate();
  useEffect(() => {
    navigate(getAuth()?.token ? "/chat" : "/", { replace: true });
  }, [navigate]);
  return null;
}
