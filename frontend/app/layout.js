import './globals.css';

export const metadata = {
  title: 'House Advantage',
  description: 'Congressional trade anomaly intelligence',
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
