import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = { title: "Plenora Operations", robots: "noindex, nofollow" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="nl"><body>{children}</body></html>;
}
