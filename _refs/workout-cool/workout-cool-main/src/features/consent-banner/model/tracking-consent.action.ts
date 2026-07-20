"use server";

import { cookies } from "next/headers";

import { Cookies } from "@/shared/constants/cookies";
import { actionClient } from "@/shared/api/safe-actions";
import { trackingConsentSchema } from "@/features/consent-banner/schema/tracking-consent.schema";

export const trackingConsentAction = actionClient.schema(trackingConsentSchema).action(async ({ parsedInput: value }) => {
  const cookiesStore = await cookies();

  const oneYearFromNow = new Date();
  oneYearFromNow.setFullYear(oneYearFromNow.getFullYear() + 1);

  cookiesStore.set({
    name: Cookies.TrackingConsent,
    value: value ? "1" : "0",
    expires: oneYearFromNow,
  });

  return value;
});
