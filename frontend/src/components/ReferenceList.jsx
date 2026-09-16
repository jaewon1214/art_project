function ReferenceList({ references = [] }) {
  if (!references.length) {
    return null;
  }

  return (
    <section className="references-section">
      <h2>참고문헌</h2>

      <div className="reference-list">
        {references.map((reference) => (
          <article
            className="reference-item"
            key={reference.source_id}
          >
            <div className="reference-id">
              {reference.source_id}
            </div>

            <div className="reference-info">
              <h3>{reference.title}</h3>

              <div className="reference-meta">
                {reference.author && (
                  <span>{reference.author}</span>
                )}

                {reference.publisher && (
                  <span>{reference.publisher}</span>
                )}

                {reference.published_at && (
                  <span>{reference.published_at}</span>
                )}

                {reference.category && (
                  <span>{reference.category}</span>
                )}
              </div>

              {reference.url && (
                <a
                  href={reference.url}
                  target="_blank"
                  rel="noreferrer"
                >
                  원문 보기
                </a>
              )}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

export default ReferenceList;