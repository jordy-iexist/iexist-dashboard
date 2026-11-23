import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

// Inter wordt bij het bouwen opgehaald en daarna vanaf de eigen server geserveerd.
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

export const metadata: Metadata = {
  title: "CSV Blog Generator | Internal",
  description: "Internal blog generation tool",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="nl" className={inter.variable}>
      <body className="antialiased">
        {children}
        <div id="portal" />
      </body>
    </html>
  );
}
