import { headers } from "next/headers";

import { EU_COUNTRY_CODES } from "@/shared/lib/location/eu-countries";

export async function getCountryCode() {
  const headersList = await headers();

  return headersList.get("x-vercel-ip-country") || "SE";
}

export async function isEU() {
  const countryCode = await getCountryCode();

  if (countryCode && EU_COUNTRY_CODES.includes(countryCode)) {
    return true;
  }

  return false;
}
