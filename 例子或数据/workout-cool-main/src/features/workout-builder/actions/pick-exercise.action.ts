"use server";

import { z } from "zod";

import { actionClient } from "@/shared/api/safe-actions";

const pickExerciseSchema = z.object({
  exerciseId: z.string(),
});

export const pickExerciseAction = actionClient.schema(pickExerciseSchema).action(async ({ parsedInput }) => {
  try {
    const { exerciseId } = parsedInput;

    // Pour l'instant, on retourne juste l'ID de l'exercice
    // Plus tard, on pourra ajouter de la logique pour marquer l'exercice comme "picked"
    // dans une base de données ou un système de préférences utilisateur

    return {
      success: true,
      exerciseId,
      message: "Exercise picked successfully",
    };
  } catch (error) {
    console.error("Error picking exercise:", error);
    return { serverError: "Failed to pick exercise" };
  }
});
