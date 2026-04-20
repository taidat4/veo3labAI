import type { Metadata } from "next";
import "./globals.css";
import { ThemeProvider } from "@/components/ThemeProvider";

export const metadata: Metadata = {
  title: "Veo3Lab — AI Video Generate",
  description: "Tạo video AI chất lượng cao với Veo 3.1 — Nhanh, đẹp, dễ dùng",
  icons: { icon: "/favicon.png", apple: "/favicon.png" },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="vi" suppressHydrationWarning>
      <head>
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap"
          rel="stylesheet"
        />
        <link
          href="https://fonts.googleapis.com/icon?family=Material+Symbols+Rounded"
          rel="stylesheet"
        />
        {/* Prevent FOUC: apply saved theme instantly */}
        <script dangerouslySetInnerHTML={{
          __html: `
            (function() {
              var t = localStorage.getItem('veo3_theme') || 'light';
              document.documentElement.className = t === 'dark' ? 'dark' : '';
            })();
          `,
        }} />
      </head>
      <body style={{ fontFamily: "'Inter', sans-serif" }}>
        <ThemeProvider>
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}
