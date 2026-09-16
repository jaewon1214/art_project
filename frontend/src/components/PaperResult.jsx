import PaperSection from "./PaperSection";
import ReferenceList from "./ReferenceList";

function PaperResult({ paper }) {
  if (!paper) {
    return null;
  }

  return (
    <article className="paper-result">
      <header className="paper-header">
        <span className="result-label">
          GENERATED PAPER
        </span>

        <h1>{paper.title}</h1>

        {paper.paper_id && (
          <p className="paper-id">
            Paper ID: {paper.paper_id}
          </p>
        )}
      </header>

      <section className="abstract-section">
        <h2>초록</h2>
        <p>{paper.abstract}</p>
      </section>

      <div className="paper-sections">
        {paper.sections?.map((section, index) => (
          <PaperSection
            key={`${section.heading}-${index}`}
            section={section}
            index={index}
          />
        ))}
      </div>

      <section className="conclusion-section">
        <h2>결론</h2>
        <p>{paper.conclusion}</p>
      </section>

      <ReferenceList
        references={paper.references}
      />
    </article>
  );
}

export default PaperResult;