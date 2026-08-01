import { redirect } from "next/navigation";

/**
 * Root page — redirects to /dashboard.
 * The dashboard layout handles the auth guard.
 */
export default function Home() {
  redirect("/dashboard");
}
