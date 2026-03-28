import Link from 'next/link';
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
            <div className="nav-brand">House Advantage</div>
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
