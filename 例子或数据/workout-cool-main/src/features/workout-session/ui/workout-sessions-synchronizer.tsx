"use client";

import { useEffect } from "react";
import { useSearchParams } from "next/navigation";

import { useSyncWorkoutSessions } from "../model/use-sync-workout-sessions";

export const WorkoutSessionsSynchronizer = () => {
  const { syncSessions } = useSyncWorkoutSessions();
  const searchParams = useSearchParams();
  const isSigninParam = searchParams.get("signin") === "true";

  useEffect(() => {
    if (isSigninParam) {
      syncSessions();
    }
  }, [isSigninParam]);

  return null;
};
