import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Mappa — Asistente Geoespacial de Puerto Rico',
  description: 'Planning and hazard assistant for Puerto Rico',
  icons: { icon: '/logo.png', apple: '/logo.png' },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es">
      <head><meta name="google" content="notranslate" /></head>
      <body>{children}</body>
    </html>
  );
}
