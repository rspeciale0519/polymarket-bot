import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PolyBot — Market Maker Dashboard",
  description: "Kalshi automated market making engine control panel",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className="antialiased">
        {children}
      </body>
    </html>
  );
}
