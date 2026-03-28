import PoliticianSearch from './politician-search';

export default function PoliticiansPage() {
  return (
    <main className="container">
      <header className="header">
        <h1>Congressional Trade Lookup</h1>
        <p>Search for a member and review their trades and audit reports.</p>
      </header>
      <PoliticianSearch />
    </main>
  );
}
