import Link from 'next/link';
import Image from 'next/image';
import './globals.css';

export const metadata = {
  title: 'House Advantage',
  description: 'Congressional trade anomaly intelligence',
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <div className="app-shell">
          <nav className="top-nav">
            <Link href="/" className="nav-brand">
              <Image
                src="/House_Advantage_Logo.png"
                alt="House Advantage"
                width={60}
                height={40}
                unoptimized
                priority
              />
              House Advantage
            </Link>
            <div className="nav-links">
              <Link href="/">Daily</Link>
              <Link href="/politicians">Politicians</Link>
            </div>
          </nav>
          {children}
        </div>
      </body>
    </html>
  );
}
