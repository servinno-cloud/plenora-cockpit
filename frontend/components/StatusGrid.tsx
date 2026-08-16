const components = ["Web", "Backend", "Database", "Mail", "Backups", "Host"];

export function StatusGrid() {
  return <section className="status-grid" aria-label="Systeemstatus">
    {components.map(name => <article className="status-card" key={name}>
      <div><span className="unknown-dot" />UNKNOWN</div><h2>{name}</h2>
      <p>Nog geen observaties</p>
    </article>)}
  </section>;
}
