import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "Business Semantic Platform",
  description: "Governança de conhecimento semântico de sistemas legados",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="pt-BR">
      <body
        style={{
          margin: 0,
          fontFamily: "system-ui, -apple-system, sans-serif",
          background: "#f6f7f9",
          color: "#1a202c",
          minHeight: "100vh",
        }}
      >
        {children}
      </body>
    </html>
  );
}
