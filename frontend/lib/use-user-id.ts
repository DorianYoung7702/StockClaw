"use client";

import { useState, useEffect } from "react";
import { getUserId } from "@/lib/api";

/**
 * React hook that returns the current user_id resolved by the backend auth layer.
 * Returns empty string until resolved — callers should skip loading when empty.
 */
export function useUserId(): string {
  const [userId, setUserId] = useState("");

  useEffect(() => {
    getUserId().then(setUserId);
  }, []);

  return userId;
}
