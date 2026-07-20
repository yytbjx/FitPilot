import { z } from "zod";

export const updateUserSchema = z.object({
  locale: z.string().optional(),
  firstName: z.string().optional(),
  lastName: z.string().optional(),
  image: z.string().optional(),
  revalidatePath: z.string().optional(),
});

export type UpdateUserInput = z.infer<typeof updateUserSchema>;
