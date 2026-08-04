import type { Metadata } from "next";
import { Geist_Mono, Instrument_Sans, Newsreader } from "next/font/google";
import "./globals.css";
import { Providers } from "@/components/providers";
import { AuthProvider } from "@/components/auth-provider";

// Three faces, three jobs; globals.css binds each to a role token.
// Interface chrome — nav, headings, labels, controls.
const instrumentSans = Instrument_Sans({
  variable: "--font-instrument-sans",
  subsets: ["latin"],
  display: "swap",
});

// Reading — answer and report prose only, never chrome. preload is off because
// the first routes a visitor hits (/login, /) never render it: a preload link
// there would spend a request on a font that page has no use for. It still
// loads on demand where the reading utilities are actually applied.
const newsreader = Newsreader({
  variable: "--font-newsreader",
  subsets: ["latin"],
  display: "swap",
  preload: false,
});

// Data — distances, indices, timestamps, citation markers, status labels.
const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Nexus AI",
  description: "A RAG research assistant grounded in your documents.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    // suppressHydrationWarning on <html> ONLY: browser extensions such as Dark
    // Reader inject attributes (e.g. data-darkreader-*) onto <html> before React
    // hydrates, causing a hydration-mismatch warning. Suppression is one level
    // deep, so this silences that extension noise without masking real mismatches
    // in the app tree.
    <html
      lang="en"
      suppressHydrationWarning
      className={`${instrumentSans.variable} ${newsreader.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <Providers>
          <AuthProvider>{children}</AuthProvider>
        </Providers>
      </body>
    </html>
  );
}
