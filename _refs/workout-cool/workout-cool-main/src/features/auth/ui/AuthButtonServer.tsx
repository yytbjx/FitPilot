import { SignUpButton } from "@/features/auth/ui/SignUpButton";
import { SignInButton } from "@/features/auth/ui/SignInButton";
import { LoggedInButton } from "@/features/auth/ui/LoggedInButton";
import { serverAuth } from "@/entities/user/model/get-server-session-user";

export const AuthButtonServer = async () => {
  const user = await serverAuth();

  if (user) {
    return <LoggedInButton user={user} />;
  }

  return (
    <div className="flex items-center gap-2">
      <SignInButton />
      <SignUpButton />
    </div>
  );
};
