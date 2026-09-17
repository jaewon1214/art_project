function PaperSection({ section, index }) {
  return (
    <section className="paper-section">
      <div className="section-title-row">
        <span className="section-number">{index + 1}</span>
        <h2>{section.heading}</h2>
      </div>

      <p className="section-content">
        {section.content}
      </p>

      {section.citations?.length > 0 && (
        <div className="citation-list">
          {section.citations.map((citation) => (
            <span
              className="citation-badge"
              key={citation}
            >
              [{citation}]
            </span>
          ))}
        </div>
      )}
    </section>
  );
}

export default PaperSection;