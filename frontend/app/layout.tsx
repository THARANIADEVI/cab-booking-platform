import type { Metadata } from "next";
import "leaflet/dist/leaflet.css";
import "./globals.css";
import { Providers } from "./providers";
export const metadata: Metadata = { title: "Cably — Your city, your way", description: "A better ride starts here. Book a ride, meet your driver and get there easy." };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="en"><body><Providers>{children}</Providers></body></html>; }
